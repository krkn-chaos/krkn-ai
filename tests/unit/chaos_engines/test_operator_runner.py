import os
import signal
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from kubernetes.config.config_exception import ConfigException

from krkn_ai.chaos_engines.operator_runner import (
    API_REQUEST_TIMEOUT,
    DEFAULT_CANCEL_GRACE_SECONDS,
    ChildIdentityChangedError,
    ChildStopUnconfirmedError,
    GROUP,
    OperatorEnv,
    PLURAL,
    VERSION,
    OperatorExecutor,
)
from krkn_ai.chaos_engines.cancellation import (
    CANCELLATION_EVENT,
    handle_cancellation_signals,
)
from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Namespace,
    Node,
    Pod,
    Service,
    ServicePort,
)
from krkn_ai.models.scenario.scenario_cpu_hog import NodeCPUHogScenario
from krkn_ai.models.scenario.scenario_dns_outage import DnsOutageScenario
from krkn_ai.models.scenario.scenario_io_hog import NodeIOHogScenario
from krkn_ai.models.scenario.scenario_memory_hog import NodeMemoryHogScenario
from krkn_ai.models.scenario.scenario_syn_flood import SynFloodScenario


def test_term_signal_requests_cooperative_cancellation():
    CANCELLATION_EVENT.clear()
    with handle_cancellation_signals():
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert CANCELLATION_EVENT.is_set()
    assert not CANCELLATION_EVENT.is_set()


def test_run_scoped_parent_monitor_is_uid_checked_and_joined():
    executor = OperatorExecutor.__new__(OperatorExecutor)
    executor.env = SimpleNamespace(
        namespace="krkn-operator",
        run_name="ai-run",
        run_uid="expected-uid",
        orchestrator_pod_name="orchestrator-pod",
    )
    executor.co = Mock()
    queried = threading.Event()

    def read_parent(*_args, **_kwargs):
        queried.set()
        return {
            "metadata": {"uid": "expected-uid"},
            "spec": {"cancelRequested": True},
            "status": {"phase": "Cancelling"},
        }

    executor.co.get_namespaced_custom_object.side_effect = read_parent
    executor._parent_identity_lost = False
    executor._cancellation_observed = False
    executor._parent_monitor_stop = threading.Event()
    executor._parent_monitor_thread = None
    executor.poll_interval = 60
    CANCELLATION_EVENT.clear()

    executor.start_parent_monitor()
    assert queried.wait(timeout=1)
    monitor = executor._parent_monitor_thread
    executor.stop_parent_monitor()

    assert monitor is not None and not monitor.is_alive()
    assert CANCELLATION_EVENT.is_set()
    executor.co.get_namespaced_custom_object.assert_called_once_with(
        GROUP,
        VERSION,
        "krkn-operator",
        "krknairuns",
        "ai-run",
        _request_timeout=API_REQUEST_TIMEOUT,
    )
    CANCELLATION_EVENT.clear()


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

    @pytest.mark.parametrize("grace", ["invalid", "0", "-1"])
    def test_cancel_grace_must_be_a_positive_integer(self, grace):
        operator_env = {
            "KRKNAI_NAMESPACE": "krkn-operator",
            "KRKNAI_RUN_NAME": "manual-run",
            "KRKNAI_RUN_UID": "run-uid",
            "KRKNAI_TARGET_REQUEST_ID": "self",
            "KRKNAI_PROVIDER": "krkn-operator",
            "KRKNAI_CLUSTER": "self",
            "KRKNAI_CANCEL_GRACE_SECONDS": grace,
        }
        with patch.dict(os.environ, operator_env, clear=True):
            with pytest.raises(ValueError, match="KRKNAI_CANCEL_GRACE_SECONDS"):
                OperatorEnv.from_environ()


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
        environment = body["spec"]["environment"]
        assert environment["KRKNAI_PARENT_RUN_NAME"] == "ai-run"
        assert environment["KRKNAI_PARENT_RUN_UID"] == "run-uid"
        assert environment["KRKNAI_CLEANUP_ATTRIBUTION"] == "krkn-ai:ai-run/run-uid/3/7"

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

    @pytest.mark.parametrize(
        ("scenario_type", "default_image"),
        [
            (
                NodeCPUHogScenario,
                "quay.io/krkn-chaos/krkn-hub-multiarch:workload-krkn-hog",
            ),
            (
                NodeMemoryHogScenario,
                "quay.io/krkn-chaos/krkn-hub-multiarch:workload-krkn-hog",
            ),
            (
                NodeIOHogScenario,
                "quay.io/krkn-chaos/krkn-hub-multiarch:workload-krkn-hog",
            ),
            (
                SynFloodScenario,
                "quay.io/krkn-chaos/krkn-hub-multiarch:workload-krkn-syn-flood",
            ),
        ],
    )
    def test_operator_scenario_run_serializes_default_and_custom_images(
        self, scenario_type, default_image
    ):
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

        if scenario_type is SynFloodScenario:
            service = Service(
                name="test-service", ports=[ServicePort(port=80, target_port=8080)]
            )
            cluster = ClusterComponents(
                namespaces=[Namespace(name="test-ns", services=[service])], nodes=[]
            )
        else:
            cluster = ClusterComponents(
                namespaces=[],
                nodes=[Node(name="worker-0", free_cpu=4.0, free_mem=8.0)],
            )

        scenario = scenario_type(cluster_components=cluster)
        image_parameter = next(
            parameter
            for parameter in scenario.parameters
            if parameter.get_name(return_krknhub_name=True) == "IMAGE"
        )
        assert image_parameter.value == default_image

        for image in (default_image, "quay.io/custom/workload:test"):
            image_parameter.value = image
            body = executor._to_scenariorun(scenario, generation_id=1, scenario_id=2)
            assert body["spec"]["environment"]["IMAGE"] == image

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

    def test_timeout_requests_child_stop_and_waits_for_terminal_phase(self):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            namespace="krkn-operator",
            scenario_timeout_seconds=10,
            cancel_grace_seconds=DEFAULT_CANCEL_GRACE_SECONDS,
            orchestrator_pod_name=None,
        )
        executor.co = Mock()
        executor.active_child = {"name": "scenario-run", "uid": "child-uid"}
        executor.co.get_namespaced_custom_object_status.side_effect = [
            {
                "metadata": {"uid": "child-uid", "resourceVersion": "rv-running"},
                "status": {"phase": "Running"},
            },
            {
                "metadata": {"uid": "child-uid", "resourceVersion": "rv-cancelled"},
                "status": {"phase": "Cancelled"},
            },
        ]
        executor.poll_interval = 0
        executor._timed_out = False
        executor._cancellation_observed = False
        executor._parent_identity_lost = False
        CANCELLATION_EVENT.clear()

        with patch(
            "krkn_ai.chaos_engines.operator_runner.time.monotonic",
            side_effect=[0, 10],
        ):
            assert executor._poll_until_terminal("scenario-run") == "Cancelled"

        executor.co.patch_namespaced_custom_object.assert_called_once_with(
            GROUP,
            VERSION,
            "krkn-operator",
            PLURAL,
            "scenario-run",
            {
                "metadata": {"uid": "child-uid", "resourceVersion": "rv-running"},
                "spec": {"cancelRequested": True},
            },
            _request_timeout=API_REQUEST_TIMEOUT,
        )
        assert executor._timed_out is True

    def test_parent_monitor_checks_uid_before_honoring_intent(self):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            namespace="krkn-operator",
            run_name="ai-run",
            run_uid="expected-uid",
            orchestrator_pod_name="orchestrator-pod",
        )
        executor.co = Mock()
        executor.co.get_namespaced_custom_object.return_value = {
            "metadata": {"uid": "replacement-uid"},
            "spec": {"cancelRequested": False},
            "status": {"phase": "Running"},
        }
        executor._parent_identity_lost = False
        CANCELLATION_EVENT.clear()

        assert executor._check_parent_intent() is True
        assert executor._parent_identity_lost is True
        assert CANCELLATION_EVENT.is_set()
        executor.co.get_namespaced_custom_object.assert_called_once_with(
            GROUP,
            VERSION,
            "krkn-operator",
            "krknairuns",
            "ai-run",
            _request_timeout=API_REQUEST_TIMEOUT,
        )

        CANCELLATION_EVENT.clear()

    def test_parent_cancel_patches_child_and_waits_for_cancelled_phase(self):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            namespace="krkn-operator",
            run_name="ai-run",
            run_uid="run-uid",
            orchestrator_pod_name="orchestrator-pod",
            scenario_timeout_seconds=60,
            cancel_grace_seconds=DEFAULT_CANCEL_GRACE_SECONDS,
        )
        executor.co = Mock()
        executor.active_child = {"name": "scenario-run", "uid": "child-uid"}
        executor.co.get_namespaced_custom_object_status.side_effect = [
            {
                "metadata": {"uid": "child-uid", "resourceVersion": "rv-running"},
                "status": {"phase": "Running"},
            },
            {
                "metadata": {"uid": "child-uid", "resourceVersion": "rv-cancelled"},
                "status": {"phase": "Cancelled"},
            },
        ]
        executor.co.get_namespaced_custom_object.return_value = {
            "metadata": {"uid": "run-uid"},
            "spec": {"cancelRequested": True},
            "status": {"phase": "Cancelling"},
        }
        executor.poll_interval = 0
        executor._timed_out = False
        executor._cancellation_observed = False
        executor._parent_identity_lost = False
        CANCELLATION_EVENT.clear()

        assert executor._poll_until_terminal("scenario-run") == "Cancelled"

        executor.co.patch_namespaced_custom_object.assert_called_once_with(
            GROUP,
            VERSION,
            "krkn-operator",
            PLURAL,
            "scenario-run",
            {
                "metadata": {"uid": "child-uid", "resourceVersion": "rv-running"},
                "spec": {"cancelRequested": True},
            },
            _request_timeout=API_REQUEST_TIMEOUT,
        )
        assert executor._cancellation_observed is True

        CANCELLATION_EVENT.clear()

    @pytest.mark.parametrize("patch_fails", [False, True])
    @pytest.mark.parametrize(
        ("cancel_requested", "clock_values"),
        [
            (False, [0, 2, 3, 4]),
            (True, [0, 0, 1, 2]),
        ],
    )
    def test_unconfirmed_stop_aborts_after_grace(
        self, cancel_requested, clock_values, patch_fails
    ):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            namespace="krkn-operator",
            scenario_timeout_seconds=1,
            cancel_grace_seconds=2,
            orchestrator_pod_name=None,
        )
        executor.co = Mock()
        executor.co.get_namespaced_custom_object_status.return_value = {
            "metadata": {"uid": "child-uid", "resourceVersion": "rv-running"},
            "status": {"phase": "Running"},
        }
        if patch_fails:
            executor.co.patch_namespaced_custom_object.side_effect = RuntimeError(
                "patch rejected"
            )
        executor.active_child = {"name": "scenario-run", "uid": "child-uid"}
        executor.poll_interval = 0
        executor._timed_out = False
        executor._cancellation_observed = False
        executor._parent_identity_lost = False
        CANCELLATION_EVENT.clear()
        if cancel_requested:
            CANCELLATION_EVENT.set()

        try:
            with (
                patch(
                    "krkn_ai.chaos_engines.operator_runner.time.monotonic",
                    side_effect=clock_values,
                ),
                pytest.raises(
                    ChildStopUnconfirmedError,
                    match=r"scenario-run \(UID child-uid\)",
                ) as exc_info,
            ):
                executor._poll_until_terminal("scenario-run")
        finally:
            CANCELLATION_EVENT.clear()

        assert "may still be active" in str(exc_info.value)
        assert executor.co.patch_namespaced_custom_object.call_count >= 1

    def test_recreated_child_is_never_patched_or_read_for_logs(self):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            namespace="krkn-operator",
            run_name="ai-run",
            run_uid="run-uid",
            orchestrator_pod_name=None,
            scenario_timeout_seconds=60,
            cancel_grace_seconds=DEFAULT_CANCEL_GRACE_SECONDS,
            target_request_id="target",
            provider="krkn-operator",
            cluster="current-cluster",
        )
        executor.config = SimpleNamespace(wait_duration=120, elastic=None)
        executor.co = Mock()
        executor.co.create_namespaced_custom_object.return_value = {
            "metadata": {"name": "scenario-run", "uid": "created-uid"}
        }
        executor.co.get_namespaced_custom_object_status.return_value = {
            "metadata": {
                "name": "scenario-run",
                "uid": "replacement-uid",
                "resourceVersion": "replacement-rv",
            },
            "status": {"phase": "Running"},
        }
        executor.core = Mock()
        executor.child_identities = []
        executor.poll_interval = 0
        CANCELLATION_EVENT.clear()
        scenario = SimpleNamespace(
            name="dummy-scenario",
            krknctl_name="dummy-scenario",
            parameters=[],
            scenario_wait_duration=lambda _: 120,
        )

        with pytest.raises(ChildIdentityChangedError, match="identity changed"):
            executor.execute(scenario, generation_id=1, scenario_id=1)

        executor.co.patch_namespaced_custom_object.assert_not_called()
        executor.co.get_namespaced_custom_object.assert_not_called()
        executor.core.read_namespaced_pod_log.assert_not_called()

        CANCELLATION_EVENT.clear()

    def test_replacement_after_terminal_child_is_not_read_for_logs(self):
        executor = OperatorExecutor.__new__(OperatorExecutor)
        executor.env = SimpleNamespace(
            namespace="krkn-operator",
            run_name="ai-run",
            run_uid="run-uid",
            orchestrator_pod_name=None,
            scenario_timeout_seconds=60,
            cancel_grace_seconds=DEFAULT_CANCEL_GRACE_SECONDS,
            target_request_id="target",
            provider="krkn-operator",
            cluster="current-cluster",
        )
        executor.config = SimpleNamespace(wait_duration=120, elastic=None)
        executor.co = Mock()
        executor.co.create_namespaced_custom_object.return_value = {
            "metadata": {"name": "scenario-run", "uid": "created-uid"}
        }
        executor.co.get_namespaced_custom_object_status.return_value = {
            "metadata": {"uid": "created-uid", "resourceVersion": "created-rv"},
            "status": {"phase": "Succeeded"},
        }
        executor.co.get_namespaced_custom_object.return_value = {
            "metadata": {
                "uid": "replacement-uid",
                "resourceVersion": "replacement-rv",
            }
        }
        executor.core = Mock()
        executor.child_identities = []
        scenario = SimpleNamespace(
            name="dummy-scenario",
            krknctl_name="dummy-scenario",
            parameters=[],
            scenario_wait_duration=lambda _: 120,
        )

        with pytest.raises(ChildIdentityChangedError, match="identity changed"):
            executor.execute(scenario, generation_id=1, scenario_id=1)

        executor.co.patch_namespaced_custom_object.assert_not_called()
        executor.core.read_namespaced_pod_log.assert_not_called()
        executor.co.get_namespaced_custom_object.assert_called_once_with(
            GROUP,
            VERSION,
            "krkn-operator",
            PLURAL,
            "scenario-run",
            _request_timeout=API_REQUEST_TIMEOUT,
        )
