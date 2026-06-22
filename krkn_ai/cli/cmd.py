import os
import sys
import uuid
import json
from contextlib import nullcontext
from kubernetes.client.rest import ApiException
from urllib3.exceptions import MaxRetryError
from krkn_ai.constants import STATUS_STARTED, STATUS_FAILED

import click
from pydantic import ValidationError
from krkn_ai.utils.logger import init_logger, get_logger

from krkn_ai.algorithm.genetic import GeneticAlgorithm
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.dashboard.manager import DashboardManager
from krkn_ai.models.custom_errors import (
    FitnessFunctionCalculationError,
    MissingScenarioError,
    PrometheusConnectionError,
    UniqueScenariosError,
)
from krkn_ai.utils.fs import read_config_from_file, save_discovery
from krkn_ai.utils.cluster_manager import ClusterManager


@click.group(context_settings={"show_default": True})
def main():
    pass


@main.command(help="Run Krkn-AI tests")
@click.option(
    "--kubeconfig",
    "-k",
    help="Path to cluster kubeconfig file. Setting this will override value in config file.",
    envvar="KUBECONFIG",
)
@click.option("--config", "-c", help="Path to krkn-ai config file.")
@click.option("--output", "-o", help="Directory to save results.", default="./")
@click.option(
    "--format",
    "-f",
    help="Format of the output file.",
    type=click.Choice(["json", "yaml"], case_sensitive=False),
    default="yaml",
)
@click.option(
    "--runner-type",
    "-r",
    type=click.Choice(["krknctl", "krknhub"], case_sensitive=False),
    help="Type of chaos engine to use.",
    default=None,
)
@click.option(
    "--param",
    "-p",
    multiple=True,
    help="Additional parameters for config file in key=value format.",
)
@click.option(
    "--seed",
    "-s",
    type=int,
    help="Random seed for reproducible runs. Overrides seed in config file.",
    default=None,
)
@click.option("-v", "--verbose", count=True, help="Increase verbosity of output.")
@click.option(
    "--monitoring",
    "-m",
    is_flag=True,
    help="Launch live monitoring dashboard in the background.",
)
@click.option(
    "--port",
    type=int,
    help="Port to run Streamlit server on when monitoring is enabled.",
    default=8501,
)
@click.pass_context
def run(
    ctx,
    kubeconfig: str,
    config: str,
    output: str = "./",
    format: str = "yaml",
    runner_type: str = None,
    param: tuple[str, ...] = (),
    seed: int = None,
    verbose: int = 0,  # Default to INFO level
    monitoring: bool = False,
    port: int = 8501,
):
    run_uuid = str(uuid.uuid4())
    new_output_path = os.path.join(output, run_uuid)
    init_logger(new_output_path, verbose >= 2)
    logger = get_logger(__name__)

    logger.info("Krkn-AI run UUID: %s", run_uuid)

    if config == "" or config is None:
        logger.error("Config file invalid.")
        exit(1)
    if not os.path.exists(config):
        logger.error("Config file not found.")
        exit(1)

    try:
        parsed_config = read_config_from_file(config, param, kubeconfig)
        logger.info("Initialized config: %s", config)
    except KeyError as err:
        logger.error("Unable to parse config file due to missing key: %s", err)
        exit(1)
    except (ValueError, ValidationError) as err:
        logger.error("Unable to parse config file: %s", err)
        exit(1)

    # Override seed from CLI if provided
    if seed is not None:
        parsed_config.seed = seed

    # Convert user-friendly string to enum if provided
    enum_runner_type = None
    if runner_type:
        if runner_type.lower() == "krknctl":
            enum_runner_type = KrknRunnerType.CLI_RUNNER
        elif runner_type.lower() == "krknhub":
            enum_runner_type = KrknRunnerType.HUB_RUNNER

    dashboard = DashboardManager(new_output_path, port) if monitoring else nullcontext()

    with dashboard:
        if (
            monitoring
            and isinstance(dashboard, DashboardManager)
            and not dashboard.is_running
        ):
            logger.warning(
                "Dashboard did not start. Continuing run without monitoring."
            )

        run_success = False
        try:
            os.makedirs(new_output_path, exist_ok=True)
            with open(os.path.join(new_output_path, "results.json"), "w") as f:
                json.dump({"status": STATUS_STARTED}, f)

            genetic = GeneticAlgorithm(
                run_uuid=run_uuid,
                config=parsed_config,
                output_dir=new_output_path,
                format=format,
                runner_type=enum_runner_type,
            )
            genetic.simulate()

            genetic.save()
            run_success = True
        except (
            MissingScenarioError,
            PrometheusConnectionError,
            UniqueScenariosError,
        ) as e:
            logger.error("%s", e)
            exit(1)
        except FitnessFunctionCalculationError as e:
            logger.error("Unable to calculate fitness function score: %s", e)
            exit(1)
        except Exception as e:
            logger.exception("Something went wrong: %s", e)
            exit(1)
        finally:
            if not run_success:
                try:
                    with open(os.path.join(new_output_path, "results.json"), "w") as f:
                        json.dump({"status": STATUS_FAILED}, f)
                except Exception:
                    pass
            logger.info("Check run.log file in '%s' for more details.", new_output_path)
            if monitoring:
                logger.info(
                    "To inspect results interactively, run: krkn-ai monitor -o %s",
                    output,
                )


@main.command(help="Monitor results from previous completed runs")
@click.option("--output", "-o", help="Directory where results are saved.", default="./")
@click.option("--port", "-p", help="Port to run Streamlit server on.", default=8501)
@click.pass_context
def monitor(ctx, output: str, port: int):
    init_logger(output, False)
    logger = get_logger(__name__)
    logger.info(
        "Starting monitoring dashboard on port %s for output directory: %s",
        port,
        output,
    )

    with DashboardManager(output, port) as dashboard:
        if not dashboard.is_running:
            logger.error("Unable to start dashboard monitor.")
            sys.exit(1)
        try:
            dashboard.wait()
        except KeyboardInterrupt:
            logger.info("Monitoring dashboard stopped.")


@main.command(help="Discover components for Krkn-AI tests")
@click.option(
    "--kubeconfig",
    "-k",
    help="Path to cluster kubeconfig file.",
    envvar="KUBECONFIG",
)
@click.option(
    "--output", "-o", help="Path to save config file.", default="./krkn-ai.yaml"
)
@click.option(
    "--namespace",
    "-n",
    help="Namespace(s) to discover components in. Supports Regex and comma separated values.",
    default=".*",
)
@click.option(
    "--pod-label",
    "-pl",
    help="Pod Label Keys(s) to filter. Supports Regex and comma separated values.",
    default=".*",
    required=False,
)
@click.option(
    "--node-label",
    "-nl",
    help="Node Label Keys(s) to filter. Supports Regex and comma separated values.",
    default=".*",
    required=False,
)
@click.option("-v", "--verbose", count=True, help="Increase verbosity of output.")
@click.option(
    "--skip-pod-name",
    help="Pod name to skip. Supports comma separated values with regex.",
    default=None,
    required=False,
)
@click.option(
    "--save-strategy",
    type=click.Choice(["skip", "overwrite", "merge"], case_sensitive=False),
    default="skip",
    help="How to save: skip, overwrite (replace), or merge (add new). Note: merge does not preserve comments inside cluster_components.",
)
@click.pass_context
def discover(
    ctx,
    kubeconfig: str,
    output: str = "./krkn-ai.yaml",
    namespace: str = ".*",
    pod_label: str = ".*",
    node_label: str = ".*",
    verbose: int = 0,
    skip_pod_name: str = None,
    save_strategy: str = "skip",
):
    init_logger(None, verbose >= 2)
    logger = get_logger(__name__)

    if kubeconfig == "" or kubeconfig is None or not os.path.exists(kubeconfig):
        logger.error("Kubeconfig file not found.")
        exit(1)

    try:
        cluster_manager = ClusterManager(kubeconfig)

        cluster_components = cluster_manager.discover_components(
            namespace_pattern=namespace,
            pod_label_pattern=pod_label,
            node_label_pattern=node_label,
            skip_pod_name=skip_pod_name,
        )
    except ApiException as e:
        logger.error("Kubernetes API error: %s", e)
        sys.exit(1)
    except MaxRetryError as e:
        logger.error("Failed to connect to Kubernetes cluster: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("An unexpected error occurred during discovery: %s", e)
        sys.exit(1)

    save_discovery(output, save_strategy, cluster_components, kubeconfig)
