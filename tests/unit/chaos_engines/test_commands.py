"""
Elasticsearch settings injected into scenario commands (#512)
"""

import shlex

import pytest

from krkn_ai.chaos_engines.commands import inject_es_config
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.config import ConfigFile, ElasticConfig, FitnessFunction


def _config(username: str = "krkn", password: str = "s3cret") -> ConfigFile:
    return ConfigFile(
        kubeconfig_file_path="/tmp/kubeconfig",
        fitness_function=FitnessFunction(query="up"),
        cluster_components=ClusterComponents(),
        elastic=ElasticConfig(
            enable=True,
            server="https://es.example.com",
            username=username,
            password=password,
        ),
    )


def _es_settings(command: str, runner_type: KrknRunnerType) -> dict:
    """Parse the command the way run_shell does and collect the ES values."""
    argv = shlex.split(command)
    if runner_type == KrknRunnerType.CLI_RUNNER:
        return {
            flag: argv[i + 1]
            for i, flag in enumerate(argv)
            if flag.startswith("--es-") or flag == "--enable-es"
        }
    return dict(
        argv[i + 1].split("=", 1)
        for i, flag in enumerate(argv)
        if flag == "-e" and argv[i + 1].startswith(("ES_", "ENABLE_ES"))
    )


RUNNERS = [KrknRunnerType.CLI_RUNNER, KrknRunnerType.HUB_RUNNER]


@pytest.mark.parametrize("runner_type", RUNNERS)
@pytest.mark.parametrize(
    "password",
    ['ab"cd', "secret\\", 'p"a"ss', "it's $HOME", "with space"],
)
def test_es_credentials_reach_runner_unchanged(runner_type, password):
    """Quotes, backslashes and spaces in credentials survive shlex.split"""
    command = inject_es_config(
        "krknctl run pod-scenarios {es_env_list}",
        _config(username=password, password=password),
        runner_type,
        True,
    )

    settings = _es_settings(command, runner_type)

    if runner_type == KrknRunnerType.CLI_RUNNER:
        assert settings["--es-password"] == password
        assert settings["--es-username"] == password
    else:
        assert settings["ES_PASSWORD"] == password
        assert settings["ES_USERNAME"] == password


@pytest.mark.parametrize(
    "runner_type, expected",
    [
        (
            KrknRunnerType.CLI_RUNNER,
            {
                "--enable-es": "True",
                "--es-server": "https://es.example.com/",
                "--es-port": "9200",
                "--es-username": "krkn",
                "--es-password": "s3cret",
                "--es-verify-certs": "True",
            },
        ),
        (
            KrknRunnerType.HUB_RUNNER,
            {
                "ENABLE_ES": "True",
                "ES_SERVER": "https://es.example.com/",
                "ES_PORT": "9200",
                "ES_USERNAME": "krkn",
                "ES_PASSWORD": "s3cret",
                "ES_VERIFY_CERTS": "True",
            },
        ),
    ],
)
def test_es_settings_for_plain_credentials(runner_type, expected):
    """Every ES setting is passed through for each runner"""
    command = inject_es_config(
        "krknctl run {es_env_list}", _config(), runner_type, True
    )

    assert _es_settings(command, runner_type) == expected


def test_es_settings_omitted_when_disabled():
    """With injection disabled the placeholder is removed and no ES values leak"""
    command = inject_es_config(
        "krknctl run pod-scenarios {es_env_list}",
        _config(),
        KrknRunnerType.CLI_RUNNER,
        False,
    )

    assert shlex.split(command) == ["krknctl", "run", "pod-scenarios"]
