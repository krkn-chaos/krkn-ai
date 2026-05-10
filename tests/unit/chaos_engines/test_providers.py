import pytest
from unittest.mock import MagicMock, patch
from krkn_ai.chaos_engines.providers.registry import ProviderRegistry
from krkn_ai.chaos_engines.providers.mock import MockProvider
from krkn_ai.chaos_engines.providers.shell import ShellProvider
from krkn_ai.chaos_engines.providers.kraken_cli import KrakenCliProvider
from krkn_ai.chaos_engines.providers.kraken_hub import KrakenHubProvider
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.chaos_engines.krkn_runner import KrknRunner
from krkn_ai.models.config import ConfigFile


def test_provider_registry():
    assert "kraken-cli" in ProviderRegistry.list_providers()
    assert "kraken-hub" in ProviderRegistry.list_providers()
    assert "mock" in ProviderRegistry.list_providers()
    assert "shell" in ProviderRegistry.list_providers()

    assert ProviderRegistry.get_provider_class("mock") == MockProvider

    with pytest.raises(ValueError):
        ProviderRegistry.get_provider_class("non-existent")


def test_mock_provider_run():
    provider = MockProvider()
    scenario = MagicMock(spec=Scenario)
    log, code, uuid, cmd = provider.run(scenario, 1)

    assert code == 0
    assert "Mock run" in log
    assert uuid is not None
    assert "mock run" in cmd


@patch("krkn_ai.chaos_engines.providers.shell.run_shell")
def test_shell_provider_run(mock_run):
    mock_run.return_value = ("hello world", 0)
    provider = ShellProvider()
    scenario = MagicMock(spec=Scenario)
    scenario.command = "echo 'hello world'"

    log, code, uuid, cmd = provider.run(scenario, 1)

    assert code == 0
    assert "hello world" in log
    assert cmd == "echo 'hello world'"


@patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client")
def test_krkn_runner_initialization_with_provider(mock_prom):
    mock_prom.return_value = MagicMock()
    config = MagicMock(spec=ConfigFile)
    config.kubeconfig_file_path = "/tmp/kubeconfig"
    config.wait_duration = 120
    config.elastic = None

    # Test Mock Runner
    runner = KrknRunner(config, "/tmp", runner_type=KrknRunnerType.MOCK_RUNNER)
    assert runner.provider.get_name() == "mock"

    # Test Shell Runner
    runner = KrknRunner(config, "/tmp", runner_type=KrknRunnerType.SHELL_RUNNER)
    assert runner.provider.get_name() == "shell"


def test_kraken_cli_command_generation():
    provider = KrakenCliProvider("/tmp/kube", 60)
    scenario = MagicMock(spec=Scenario)
    scenario.parameters = []
    scenario.krknctl_name = "pod-scenario"

    cmd = provider._generate_command(scenario)
    assert "krknctl run pod-scenario" in cmd
    assert "--kubeconfig /tmp/kube" in cmd
    assert "--wait-duration 60" in cmd


def test_kraken_hub_command_generation():
    provider = KrakenHubProvider("/tmp/kube", 60)
    scenario = MagicMock(spec=Scenario)
    scenario.parameters = []
    scenario.krknhub_image = "quay.io/kraken/pod-scenario"

    cmd = provider._generate_command(scenario)
    assert "podman run" in cmd
    assert "quay.io/kraken/pod-scenario" in cmd
    assert "/tmp/kube:/home/krkn/.kube/config:Z" in cmd
