from krkn_ai.models.app import KrknRunnerType
from krkn_ai.models.config import ConfigFile
from krkn_ai.models.scenario.base import Scenario

PODMAN_TEMPLATE = 'podman run -e PUBLISH_KRAKEN_STATUS="False" -e TELEMETRY_PROMETHEUS_BACKUP="False" -e WAIT_DURATION={wait_duration} {env_list} {{es_env_list}} --net=host -v {kubeconfig}:/home/krkn/.kube/config:Z {image}'

PODMAN_ES_TEMPLATE = ' -e ENABLE_ES="True" -e ES_SERVER="{server}" -e ES_PORT="{port}" -e ES_USERNAME="{username}" -e ES_PASSWORD="{password}" -e ES_VERIFY_CERTS="{verify_certs}" '

KRKNCTL_TEMPLATE = "krknctl run {name} --telemetry-prometheus-backup False --wait-duration {wait_duration} --kubeconfig {kubeconfig} {env_list} {{es_env_list}}"

KRKNCTL_ES_TEMPLATE = ' --enable-es True --es-server "{server}" --es-port "{port}" --es-username "{username}" --es-password "{password}" --es-verify-certs "{verify_certs}" '


def build_scenario_command(
    scenario: Scenario, config: ConfigFile, runner_type: KrknRunnerType
) -> str:
    if runner_type == KrknRunnerType.HUB_RUNNER:
        env_list = ""
        for parameter in scenario.parameters:
            env_list += f' -e {parameter.get_name(return_krknhub_name=True)}="{parameter.get_value()}" '

        command = PODMAN_TEMPLATE.format(
            wait_duration=scenario.scenario_wait_duration(config.wait_duration),
            env_list=env_list,
            kubeconfig=config.kubeconfig_file_path,
            image=scenario.krknhub_image,
        )
        return command
    elif runner_type == KrknRunnerType.CLI_RUNNER:
        env_list = ""
        for parameter in scenario.parameters:
            param_name = parameter.get_name(return_krknhub_name=False)
            env_list += f'--{param_name} "{parameter.get_value()}" '

        command = KRKNCTL_TEMPLATE.format(
            wait_duration=scenario.scenario_wait_duration(config.wait_duration),
            env_list=env_list,
            kubeconfig=config.kubeconfig_file_path,
            name=scenario.krknctl_name,
        )
        return command
    raise Exception("Unsupported runner type")


def inject_es_config(
    command: str, config: ConfigFile, runner_type: KrknRunnerType, enable: bool
) -> str:
    if not enable or config.elastic is None or config.elastic.enable is False:
        return command.replace("{es_env_list}", "")

    es_env_list = ""
    if runner_type == KrknRunnerType.HUB_RUNNER:
        es_env_list = PODMAN_ES_TEMPLATE.format(
            server=config.elastic.server,
            port=config.elastic.port,
            username=config.elastic.username,
            password=config.elastic.password,
            verify_certs=config.elastic.verify_certs,
        )
    elif runner_type == KrknRunnerType.CLI_RUNNER:
        es_env_list = KRKNCTL_ES_TEMPLATE.format(
            server=config.elastic.server,
            port=config.elastic.port,
            username=config.elastic.username,
            password=config.elastic.password,
            verify_certs=config.elastic.verify_certs,
        )

    return command.replace("{es_env_list}", es_env_list)
