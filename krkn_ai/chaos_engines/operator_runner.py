import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from kubernetes import client, config as kube_config
from kubernetes.config.config_exception import ConfigException

from krkn_ai.models.config import ConfigFile
from krkn_ai.models.scenario.base import CompositeScenario, Scenario


GROUP = "krkn.krkn-chaos.dev"
VERSION = "v1alpha1"
PLURAL = "krknscenarioruns"
TERMINAL_PHASES = {"Succeeded", "Failed", "PartiallyFailed"}

DEFAULT_SCENARIO_TIMEOUT_SECONDS = 60 * 60


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
        self.poll_interval = 5

    def execute(
        self, scenario: Scenario, generation_id: int, scenario_id: int | str
    ) -> tuple[str, int]:
        if isinstance(scenario, CompositeScenario):
            raise NotImplementedError("composite scenarios unsupported in operator MVP")

        body = self._to_scenariorun(scenario, generation_id, scenario_id)
        created = self.co.create_namespaced_custom_object(
            GROUP, VERSION, self.env.namespace, PLURAL, body
        )
        name = created["metadata"]["name"]
        try:
            phase = self._poll_until_terminal(name)
        except TimeoutError as error:
            return str(error), 1

        pod = self._pod_name(name)
        log = (
            self.core.read_namespaced_pod_log(
                pod, self.env.namespace, container="scenario"
            )
            if pod
            else ""
        )
        return log, 0 if phase == "Succeeded" else 1

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

    def _poll_until_terminal(self, name: str) -> str:
        deadline = time.monotonic() + self.env.scenario_timeout_seconds
        while time.monotonic() < deadline:
            resource = self.co.get_namespaced_custom_object_status(
                GROUP, VERSION, self.env.namespace, PLURAL, name
            )
            phase = resource.get("status", {}).get("phase")
            if phase in TERMINAL_PHASES:
                return phase
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.poll_interval, remaining))
        raise TimeoutError(
            f"KrknScenarioRun {name} did not reach a terminal phase within "
            f"{self.env.scenario_timeout_seconds} seconds"
        )

    def _pod_name(self, name: str) -> Optional[str]:
        resource = self.co.get_namespaced_custom_object(
            GROUP, VERSION, self.env.namespace, PLURAL, name
        )
        jobs = resource.get("status", {}).get("clusterJobs", [])
        return jobs[0].get("podName") if jobs else None
