import os

import click
from pydantic import ValidationError
from krkn_ai.utils.logger import init_logger, get_logger

from krkn_ai.algorithm.genetic import GeneticAlgorithm
from krkn_ai.models.app import AppContext, KrknRunnerType
from krkn_ai.models.custom_errors import PrometheusConnectionError
from krkn_ai.utils.fs import read_config_from_file
from krkn_ai.templates.generator import create_krkn_ai_template
from krkn_ai.utils.cluster_manager import ClusterManager


@click.group(context_settings={"show_default": True})
def main():
    pass

@main.command(
    help='Run Krkn-AI tests'
)
@click.option('--config', '-c', help='Path to krkn-ai config file.')
@click.option('--output', '-o', help='Directory to save results.')
@click.option('--format', '-f', help='Format of the output file.',
    type=click.Choice(['json', 'yaml'], case_sensitive=False),
    default='yaml'
)
@click.option('--runner-type', '-r', 
              type=click.Choice(['krknctl', 'krknhub'], case_sensitive=False),
              help='Type of chaos engine to use.', default=None)
@click.option(
    '--param', '-p',
    multiple=True,
    help='Additional parameters for config file in key=value format.',
    default=[]
)
@click.option('-v', '--verbose', count=True, help='Increase verbosity of output.')
@click.pass_context
def run(ctx,
    config: str,
    output: str = "./",
    format: str = 'yaml',
    runner_type: str = None,
    param: list[str] = None,
    verbose: int = 0       # Default to INFO level
):
    init_logger(output, verbose >= 2)
    logger = get_logger(__name__)

    if config == '' or config is None:
        logger.error("Config file invalid.")
        exit(1)
    if not os.path.exists(config):
        logger.error("Config file not found.")
        exit(1)

    try:
        parsed_config = read_config_from_file(config, param)
        logger.info("Initialized config: %s", config)
    except ValidationError as err:
        logger.error("Unable to parse config file: %s", err)
        exit(1)

    # Convert user-friendly string to enum if provided
    enum_runner_type = None
    if runner_type:
        if runner_type.lower() == 'krknctl':
            enum_runner_type = KrknRunnerType.CLI_RUNNER
        elif runner_type.lower() == 'krknhub':
            enum_runner_type = KrknRunnerType.HUB_RUNNER

    try:
        genetic = GeneticAlgorithm(
            parsed_config,
            output_dir=output,
            format=format,
            runner_type=enum_runner_type
        )
        genetic.simulate()

        genetic.save()
    except PrometheusConnectionError as e:
        logger.error("%s", e)
        exit(1)
    except Exception as e:
        logger.exception("Something went wrong: %s", e)
        exit(1)
    finally:
        logger.info("Check run.log file in '%s' for more details.", output)


@main.command(
    help='Discover components for Krkn-AI tests'
)
@click.option('--kubeconfig', '-k', help='Path to cluster kubeconfig file.', default=os.getenv('KUBECONFIG', None))
@click.option('--output', '-o', help='Path to save config file.', default='./krkn-ai.yaml')
@click.option('--namespace', '-n', help='Namespace(s) to discover components in. Supports Regex and comma separated values.', default='.*')
@click.option('--pod-label', '-pl', help='Pod Label Keys(s) to filter. Supports Regex and comma separated values.', default='.*', required=False)
@click.option('--node-label', '-nl', help='Node Label Keys(s) to filter. Supports Regex and comma separated values.', default='.*', required=False)
@click.option('-v', '--verbose', count=True, help='Increase verbosity of output.')
@click.pass_context
def discover(
    ctx,
    kubeconfig: str,
    output: str = "./",
    namespace: str = "*",
    pod_label: str = ".*",
    node_label: str = ".*",
    verbose: int = 0
):
    init_logger(None, verbose >= 2)
    logger = get_logger(__name__)

    if kubeconfig == '' or kubeconfig is None:
        logger.warning("Kubeconfig file not found.")
        exit(1)

    cluster_manager = ClusterManager(kubeconfig)

    cluster_components = cluster_manager.discover_components(
        namespace_pattern=namespace,
        pod_label_pattern=pod_label,
        node_label_pattern=node_label
    )

    cluster_components_data = cluster_components.model_dump(mode='json', warnings='none')

    template = create_krkn_ai_template(kubeconfig, cluster_components_data)

    with open(output, 'w') as f:
        f.write(template)

    logger.info("Saved component configuration to %s", output)
