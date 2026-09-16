import os
from types import SimpleNamespace
from unittest.mock import patch

from kubernetes.config.config_exception import ConfigException

from krkn_ai.chaos_engines.operator_runner import OperatorExecutor


class TestOperatorExecutorAuthentication:
    def test_falls_back_to_cli_kubeconfig_outside_cluster(self):
        config = type("Config", (), {"kubeconfig_file_path": "/tmp/test-kubeconfig"})()
        operator_env = {
            "KRKNAI_NAMESPACE": "krkn-operator",
            "KRKNAI_RUN_NAME": "manual-run",
            "KRKNAI_RUN_UID": "run-uid",
            "KRKNAI_ORCHESTRATOR_POD_NAME": "manual-run-a1b2c3d4",
            "KRKNAI_TARGET_REQUEST_ID": "self",
            "KRKNAI_PROVIDER": "krkn-operator",
            "KRKNAI_CLUSTER": "self",
        }

        with (
            patch.dict(os.environ, operator_env, clear=False),
            patch(
                "krkn_ai.chaos_engines.operator_runner.kube_config.load_incluster_config",
                side_effect=ConfigException("not running in a cluster"),
            ) as load_incluster,
            patch(
                "krkn_ai.chaos_engines.operator_runner.kube_config.load_kube_config"
            ) as load_kubeconfig,
        ):
            OperatorExecutor(config)

        load_incluster.assert_called_once_with()
        load_kubeconfig.assert_called_once_with(config_file="/tmp/test-kubeconfig")


class TestOperatorExecutorScenarioRun:
    def test_uses_current_scenario_reference_contract(self):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            target_request_id="target",
            provider="krkn-operator",
            cluster="current-cluster",
            run_name="ai-run",
            orchestrator_pod_name="ai-run-a1b2c3d4",
            run_uid="run-uid",
        )
        executor.config = SimpleNamespace(wait_duration=120, elastic=None)
        scenario = SimpleNamespace(
            name="dummy-scenario",
            krknctl_name="dummy-scenario",
            parameters=[],
            scenario_wait_duration=lambda _: 120,
        )

        body = executor._to_scenariorun(scenario, generation_id=3, scenario_id=7)

        assert body["spec"]["scenario"] == {
            "name": "dummy-scenario",
            "private": False,
        }
        assert body["spec"]["maxRetries"] == 0
        assert "scenarioName" not in body["spec"]
        assert "scenarioImage" not in body["spec"]
        assert body["metadata"]["labels"] == {
            "krkn.dev/ai-run": "ai-run",
            "krkn.dev/orchestrator-pod": "ai-run-a1b2c3d4",
            "krkn.dev/scenario-id": "7",
            "krkn.dev/generation-id": "3",
            "krkn.dev/scenario-name": "dummy-scenario",
        }
