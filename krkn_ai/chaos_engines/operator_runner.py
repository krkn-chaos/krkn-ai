import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from kubernetes import client, config as kube_config
from kubernetes.config.config_exception import ConfigException

from krkn_ai.models.config import ConfigFile
from krkn_ai.models.scenario.base import CompositeScenario, Scenario
from kubernetes.client.rest import ApiException

from krkn_ai.chaos_engines.cancellation import (
    CancellationRequested,
    CANCELLATION_EVENT,
    cancellation_requested,
    request_cancellation,
)
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


GROUP = "krkn.krkn-chaos.dev"
VERSION = "v1alpha1"
PLURAL = "krknscenarioruns"
TERMINAL_PHASES = {"Succeeded", "Failed", "PartiallyFailed", "Cancelled"}

API_REQUEST_TIMEOUT = (5, 30)
DEFAULT_SCENARIO_TIMEOUT_SECONDS = 60 * 60


class ChildIdentityChangedError(RuntimeError):
    """The observed child no longer matches the resource created by this run."""


@dataclass(frozen=True)
class OperatorEnv:
    namespace: str
    run_name: str
    run_uid: str
    orchestrator_pod_name: Optional[str]
    target_request_id: str
    provider: str
    cluster: str
    scenario_timeout_seconds: int

    @classmethod
    def from_environ(cls) -> "OperatorEnv":
        required = {
            "namespace": "KRKNAI_NAMESPACE",
            "run_name": "KRKNAI_RUN_NAME",
            "run_uid": "KRKNAI_RUN_UID",
            "target_request_id": "KRKNAI_TARGET_REQUEST_ID",
            "provider": "KRKNAI_PROVIDER",
            "cluster": "KRKNAI_CLUSTER",
        }
        missing = [
            env_name
            for field, env_name in required.items()
            if not os.environ.get(env_name)
        ]
        if missing:
            raise ValueError(
                "missing required operator environment variable(s): "
                + ", ".join(missing)
            )

        raw_timeout = os.environ.get(
            "KRKNAI_SCENARIO_TIMEOUT_SECONDS",
            str(DEFAULT_SCENARIO_TIMEOUT_SECONDS),
        )
        try:
            scenario_timeout_seconds = int(raw_timeout)
        except ValueError as exc:
            raise ValueError(
                "KRKNAI_SCENARIO_TIMEOUT_SECONDS must be a positive integer"
            ) from exc
        if scenario_timeout_seconds <= 0:
            raise ValueError(
                "KRKNAI_SCENARIO_TIMEOUT_SECONDS must be a positive integer"
            )

        return cls(
            namespace=os.environ["KRKNAI_NAMESPACE"],
            run_name=os.environ["KRKNAI_RUN_NAME"],
            run_uid=os.environ["KRKNAI_RUN_UID"],
            orchestrator_pod_name=os.environ.get("KRKNAI_ORCHESTRATOR_POD_NAME"),
            target_request_id=os.environ["KRKNAI_TARGET_REQUEST_ID"],
            provider=os.environ["KRKNAI_PROVIDER"],
            cluster=os.environ["KRKNAI_CLUSTER"],
            scenario_timeout_seconds=scenario_timeout_seconds,
        )


class OperatorExecutor:
    def __init__(self, config: ConfigFile):
        try:
            kube_config.load_incluster_config()
        except ConfigException:
            # Manual runs use the kubeconfig already resolved by the CLI.
            kube_config.load_kube_config(config_file=config.kubeconfig_file_path)
        self.co = client.CustomObjectsApi()
        self.core = client.CoreV1Api()
        self.env = OperatorEnv.from_environ()
        self.config = config
        self.active_child: Optional[dict[str, str]] = None
        self.child_identities: list[dict[str, str]] = []
        self._timed_out = False
        self._cancellation_observed = False
        self._parent_identity_lost = False
        self.poll_interval = 5
        self._parent_monitor_stop = threading.Event()
        self._parent_monitor_thread: Optional[threading.Thread] = None

    def start_parent_monitor(self) -> None:
        if not self.env.orchestrator_pod_name or (
            self._parent_monitor_thread is not None
            and self._parent_monitor_thread.is_alive()
        ):
            return
        self._parent_monitor_stop.clear()
        self._parent_monitor_thread = threading.Thread(
            target=self._monitor_parent_intent,
            name=f"krkn-ai-parent-{self.env.run_name}",
            daemon=True,
        )
        self._parent_monitor_thread.start()

    def stop_parent_monitor(self) -> None:
        thread = self._parent_monitor_thread
        if thread is None:
            return
        self._parent_monitor_stop.set()
        thread.join()
        self._parent_monitor_thread = None

    def _monitor_parent_intent(self) -> None:
        while not self._parent_monitor_stop.is_set():
            if self._check_parent_intent():
                return
            self._parent_monitor_stop.wait(self.poll_interval)

    def execute(
        self, scenario: Scenario, generation_id: int, scenario_id: int | str
    ) -> tuple[str, int, Optional[str]]:
        if isinstance(scenario, CompositeScenario):
            raise NotImplementedError("composite scenarios unsupported in operator MVP")

        self._timed_out = False
        self._cancellation_observed = False
        self._parent_identity_lost = False
        self._check_parent_intent()
        if cancellation_requested():
            raise CancellationRequested()

        body = self._to_scenariorun(scenario, generation_id, scenario_id)
        created = self.co.create_namespaced_custom_object(
            GROUP,
            VERSION,
            self.env.namespace,
            PLURAL,
            body,
            _request_timeout=API_REQUEST_TIMEOUT,
        )
        metadata = created.get("metadata", {})
        name = metadata["name"]
        child_uid = metadata.get("uid")
        if not child_uid:
            raise ChildIdentityChangedError(
                f"Created KrknScenarioRun {name} has no UID; refusing to observe it"
            )
        self.active_child = {"name": name, "uid": child_uid}
        self.child_identities.append(dict(self.active_child))
        phase = self._poll_until_terminal(name)
        self._check_parent_intent()
        if phase == "Cancelled" and not self._timed_out:
            self._cancellation_observed = True
            request_cancellation()

        pod = None
        try:
            pod = self._pod_name(name)
        except ApiException as error:
            logger.warning(
                "Unable to inspect stopped child %s for logs: %s", name, error
            )
        log = ""
        if pod:
            try:
                log = self.core.read_namespaced_pod_log(
                    pod,
                    self.env.namespace,
                    container="scenario",
                    _request_timeout=API_REQUEST_TIMEOUT,
                )
            except ApiException as error:
                logger.warning(
                    "Unable to retrieve logs for stopped child %s: %s", name, error
                )
        if self._timed_out and not self._cancellation_observed:
            message = (
                f"KrknScenarioRun {name} exceeded the "
                f"{self.env.scenario_timeout_seconds} second timeout and was "
                "stopped after reaching a terminal phase"
            )
            return f"{message}\n{log}".strip(), 1, None
        if phase == "Cancelled":
            return log, 0, "cancelled"
        return log, 0 if phase == "Succeeded" else 1, None

    def _to_scenariorun(
        self, scenario: Scenario, generation_id: int, scenario_id: int | str
    ) -> dict[str, Any]:
        env: dict[str, str] = {
            "PUBLISH_KRAKEN_STATUS": "False",
            "TELEMETRY_PROMETHEUS_BACKUP": "False",
            "WAIT_DURATION": str(
                scenario.scenario_wait_duration(self.config.wait_duration)
            ),
        }
        env.update(
            {
                "KRKNAI_PARENT_RUN_NAME": self.env.run_name,
                "KRKNAI_PARENT_RUN_UID": self.env.run_uid,
                "KRKNAI_CLEANUP_ATTRIBUTION": (
                    f"krkn-ai:{self.env.run_name}/{self.env.run_uid}/"
                    f"{generation_id}/{scenario_id}"
                ),
            }
        )
        for parameter in scenario.parameters:
            env[parameter.get_name(return_krknhub_name=True)] = str(
                parameter.get_value(return_krknhub_name=True)
            )

        scenario_name = scenario.krknctl_name or scenario.name
        spec = {
            "targetRequestId": self.env.target_request_id,
            "targetClusters": {self.env.provider: [self.env.cluster]},
            "scenario": {
                "name": scenario_name,
                "private": False,
            },
            "maxRetries": 0,
            "environment": {key: str(value) for key, value in env.items()},
        }
        labels = {
            "krkn.dev/ai-run": self.env.run_name,
            "krkn.dev/scenario-id": str(scenario_id),
            "krkn.dev/generation-id": str(generation_id),
            "krkn.dev/scenario-name": scenario_name,
        }
        metadata: dict[str, Any] = {
            "generateName": f"{self.env.run_name}-",
            "labels": labels,
        }
        if self.env.orchestrator_pod_name:
            labels["krkn.dev/orchestrator-pod"] = self.env.orchestrator_pod_name
            metadata["ownerReferences"] = [
                {
                    "apiVersion": f"{GROUP}/{VERSION}",
                    "kind": "KrknAIRun",
                    "name": self.env.run_name,
                    "uid": self.env.run_uid,
                    "controller": True,
                    "blockOwnerDeletion": True,
                }
            ]

        return {
            "apiVersion": f"{GROUP}/{VERSION}",
            "kind": "KrknScenarioRun",
            "metadata": metadata,
            "spec": spec,
        }

    def _check_parent_intent(self) -> bool:
        if not self.env.orchestrator_pod_name:
            return False
        if cancellation_requested():
            return True
        try:
            parent = self.co.get_namespaced_custom_object(
                GROUP,
                VERSION,
                self.env.namespace,
                "krknairuns",
                self.env.run_name,
                _request_timeout=API_REQUEST_TIMEOUT,
            )
        except ApiException as error:
            if error.status == 404:
                self._parent_identity_lost = True
                request_cancellation()
                return True
            logger.warning(
                "Unable to read parent KrknAIRun during cancellation monitor: %s", error
            )
            return False
        except Exception as error:
            logger.warning(
                "Unable to read parent KrknAIRun during cancellation monitor: %s", error
            )
            return False

        metadata = parent.get("metadata", {})
        if metadata.get("uid") != self.env.run_uid:
            self._parent_identity_lost = True
            request_cancellation()
            return True
        status = parent.get("status", {})
        if parent.get("spec", {}).get("cancelRequested") or status.get("phase") in {
            "Cancelling",
            "Cancelled",
        }:
            request_cancellation()
            self._cancellation_observed = True
            return True
        return False

    def _request_child_cancellation(self, name: str) -> bool:
        identity = self.active_child
        if (
            identity is None
            or identity.get("name") != name
            or not identity.get("uid")
            or not identity.get("resourceVersion")
        ):
            logger.error(
                "Refusing to cancel child %s without its recorded UID and resourceVersion",
                name,
            )
            return False
        try:
            self.co.patch_namespaced_custom_object(
                GROUP,
                VERSION,
                self.env.namespace,
                PLURAL,
                name,
                {
                    "metadata": {
                        "uid": identity["uid"],
                        "resourceVersion": identity["resourceVersion"],
                    },
                    "spec": {"cancelRequested": True},
                },
                _request_timeout=API_REQUEST_TIMEOUT,
            )
            return True
        except Exception as error:
            logger.warning(
                "Unable to persist cancellation request for child %s: %s", name, error
            )
            return False

    def _observe_child(self, resource: dict[str, Any], name: str) -> None:
        identity = self.active_child
        metadata = resource.get("metadata", {})
        if (
            identity is None
            or identity.get("name") != name
            or not identity.get("uid")
            or metadata.get("uid") != identity["uid"]
        ):
            observed_uid = metadata.get("uid")
            expected_uid = identity.get("uid") if identity else None
            raise ChildIdentityChangedError(
                f"KrknScenarioRun {name} identity changed "
                f"(expected UID {expected_uid}, observed UID {observed_uid}); "
                "refusing further access"
            )
        resource_version = metadata.get("resourceVersion")
        if not resource_version:
            raise ChildIdentityChangedError(
                f"KrknScenarioRun {name} has no resourceVersion; refusing further access"
            )
        identity["resourceVersion"] = resource_version

    def _poll_until_terminal(self, name: str) -> str:
        deadline = time.monotonic() + self.env.scenario_timeout_seconds
        stop_requested = False
        timeout_requested = False
        while True:
            resource = self.co.get_namespaced_custom_object_status(
                GROUP,
                VERSION,
                self.env.namespace,
                PLURAL,
                name,
                _request_timeout=API_REQUEST_TIMEOUT,
            )
            self._observe_child(resource, name)
            phase = resource.get("status", {}).get("phase")
            if phase in TERMINAL_PHASES:
                self._timed_out = timeout_requested
                return phase

            if self._check_parent_intent():
                self._cancellation_observed = not self._parent_identity_lost
            if not stop_requested:
                if cancellation_requested():
                    self._cancellation_observed = not self._parent_identity_lost
                    stop_requested = self._request_child_cancellation(name)
                elif time.monotonic() >= deadline:
                    timeout_requested = True
                    stop_requested = self._request_child_cancellation(name)

            if cancellation_requested():
                time.sleep(self.poll_interval)
            else:
                CANCELLATION_EVENT.wait(self.poll_interval)

    def _pod_name(self, name: str) -> Optional[str]:
        resource = self.co.get_namespaced_custom_object(
            GROUP,
            VERSION,
            self.env.namespace,
            PLURAL,
            name,
            _request_timeout=API_REQUEST_TIMEOUT,
        )
        self._observe_child(resource, name)
        jobs = resource.get("status", {}).get("clusterJobs", [])
        return jobs[0].get("podName") if jobs else None
