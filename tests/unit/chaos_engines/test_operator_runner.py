import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from kubernetes.config.config_exception import ConfigException

from krkn_ai.chaos_engines.operator_runner import OperatorExecutor
from krkn_ai.models.cluster_components import ClusterComponents, Namespace, Pod
from krkn_ai.models.scenario.scenario_dns_outage import DnsOutageScenario


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
        assert body["metadata"]["ownerReferences"][0]["uid"] == "run-uid"

    def test_dns_outage_uses_the_selected_pod_namespace(self):
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
        scenario = DnsOutageScenario(
            cluster_components=ClusterComponents(
                namespaces=[Namespace(name="robot-shop", pods=[Pod(name="payment")])],
                nodes=[],
            )
        )

        body = executor._to_scenariorun(scenario, generation_id=3, scenario_id=7)

        assert body["spec"]["environment"]["NAMESPACE"] == "robot-shop"
        assert body["spec"]["environment"]["POD_NAME"] == "payment"

    def test_manual_scenario_run_has_no_owner_reference(self):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            target_request_id="target",
            provider="krkn-operator",
            cluster="current-cluster",
            run_name="manual-run",
            orchestrator_pod_name=None,
            run_uid="manual-uid",
        )
        executor.config = SimpleNamespace(wait_duration=120, elastic=None)
        scenario = SimpleNamespace(
            name="dummy-scenario",
            krknctl_name="dummy-scenario",
            parameters=[],
            scenario_wait_duration=lambda _: 120,
        )

        body = executor._to_scenariorun(scenario, generation_id=3, scenario_id=7)

        assert "ownerReferences" not in body["metadata"]
        assert "krkn.dev/orchestrator-pod" not in body["metadata"]["labels"]

    def test_operator_scenario_run_omits_elasticsearch_credentials(self):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            target_request_id="target",
            provider="krkn-operator",
            cluster="current-cluster",
            run_name="ai-run",
            orchestrator_pod_name="ai-run-a1b2c3d4",
            run_uid="run-uid",
        )
        executor.config = SimpleNamespace(
            wait_duration=120,
            elastic=SimpleNamespace(
                enable=True,
                server="https://elasticsearch.example.test",
                port=9200,
                username="username",
                password="password",
                verify_certs=True,
            ),
        )
        scenario = SimpleNamespace(
            name="dummy-scenario",
            krknctl_name="dummy-scenario",
            parameters=[],
            scenario_wait_duration=lambda _: 120,
        )

        body = executor._to_scenariorun(scenario, generation_id=3, scenario_id=7)

        assert "ES_PASSWORD" not in body["spec"]["environment"]
        assert "ES_USERNAME" not in body["spec"]["environment"]

    def test_polling_times_out_when_scenario_run_never_terminates(self):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            namespace="krkn-operator", scenario_timeout_seconds=10
        )
        executor.co = Mock()
        executor.poll_interval = 5

        with (
            patch(
                "krkn_ai.chaos_engines.operator_runner.time.monotonic",
                side_effect=[0, 0, 0, 10],
            ),
            patch("krkn_ai.chaos_engines.operator_runner.time.sleep"),
            pytest.raises(TimeoutError, match="did not reach a terminal phase"),
        ):
            executor._poll_until_terminal("scenario-run")
