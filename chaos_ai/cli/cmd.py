import json
import logging
import os

import click
from pydantic import ValidationError

from chaos_ai.algorithm.genetic import GeneticAlgorithm
from chaos_ai.models.app import AppContext, KrknRunnerType
from chaos_ai.utils.cluster_manager import ClusterManager
from chaos_ai.utils.fs import read_config_from_file, save_data_to_file
from chaos_ai.utils.logger import (
    get_module_logger,
    set_global_log_level,
    verbosity_to_level,
)


@click.group()
def main():
    pass

@main.command(
    help='Run Chaos AI tests'
)
@click.option('--config', '-c', help='Path to chaos AI config file.')
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
    log_level = verbosity_to_level(verbose)
    ctx.obj = AppContext(verbose=log_level)
    
    # Set global log level so all modules use the correct verbosity
    set_global_log_level(log_level)

    logger = get_module_logger(__name__)

    if config == '' or config is None:
        logger.warning("Config file invalid.")
        exit(1)
    if not os.path.exists(config):
        logger.warning("Config file not found.")
        exit(1)

    try:
        logger.debug("Config File: %s", config)
        parsed_config = read_config_from_file(config, param)
        logger.debug("Successfully parsed config!")
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

    genetic = GeneticAlgorithm(
        parsed_config,
        output_dir=output,
        format=format,
        runner_type=enum_runner_type
    )
    genetic.simulate()

    genetic.save()


@main.command(
    help='Discover components for Chaos AI tests'
)
@click.option('--kubeconfig', '-k', help='Path to cluster kubeconfig file.', default=os.getenv('KUBECONFIG', None))
@click.option('--output', '-o', help='Path to save config file.', default='./chaos-ai.yaml')
@click.option('--namespace', '-n', help='Namespace(s) to discover components in. Supports Regex and comma separated values.', default='.*')
@click.option('--pod-label', '-l', help='Pod Label Keys(s) to filter. Supports Regex and comma separated values.', default='.*')
@click.option('-v', '--verbose', count=True, help='Increase verbosity of output.')
@click.pass_context
def discover(
    ctx,
    kubeconfig: str,
    output: str = "./",
    namespace: str = "*",
    pod_label: str = ".*",
    verbose: int = 0
):
    log_level = verbosity_to_level(verbose)
    ctx.obj = AppContext(verbose=log_level)
    
    # Set global log level so all modules use the correct verbosity
    set_global_log_level(log_level)

    logger = get_module_logger(__name__)

    if kubeconfig == '' or kubeconfig is None:
        logger.warning("Kubeconfig file not found.")
        exit(1)
    
    cluster_manager = ClusterManager(kubeconfig)

    namespace_components = cluster_manager.discover_components(
        namespace_pattern=namespace,
        pod_label_pattern=pod_label
    )

    json_data = [ns.model_dump(mode='json', warnings='none') for ns in namespace_components]

    save_data_to_file(json_data, output)
    logger.info("Saved component configuration to %s", output)