import math
from typing import Optional
from pydantic import BaseModel, Field, PrivateAttr
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import BaseParameter


class DummyEndParameter(BaseParameter):
    krknhub_name: str = "END"
    krknctl_name: str = "duration"
    value: int = 10


class DummyExitStatusParameter(BaseParameter):
    krknhub_name: str = "EXIT_STATUS"
    krknctl_name: str = "exit-status"
    value: int = 0


class NamespaceParameter(BaseParameter):
    krknhub_name: str = "NAMESPACE"
    krknctl_name: str = "namespace"
    value: str = ""


class PodLabelParameter(BaseParameter):
    krknhub_name: str = "POD_LABEL"
    krknctl_name: str = "pod-label"
    value: str = ""  # Example: service=payment


class NamePatternParameter(BaseParameter):
    krknhub_name: str = "NAME_PATTERN"
    krknctl_name: str = "name-pattern"
    value: str = ".*"


class DisruptionCountParameter(BaseParameter):
    krknhub_name: str = "DISRUPTION_COUNT"
    krknctl_name: str = "disruption-count"
    value: int = 1


class KillTimeoutParameter(BaseParameter):
    krknhub_name: str = "KILL_TIMEOUT"
    krknctl_name: str = "kill-timeout"
    value: int = 60


class ExpRecoveryTimeParameter(BaseParameter):
    krknhub_name: str = "EXPECTED_RECOVERY_TIME"
    krknctl_name: str = "expected-recovery-time"
    value: int = 60


class DurationParameter(BaseParameter):
    krknhub_name: str = "DURATION"
    krknctl_name: str = "chaos-duration"
    value: int = 60


class PodSelectorParameter(BaseParameter):
    krknhub_name: str = "POD_SELECTOR"
    krknctl_name: str = "pod-selector"
    value: str = ""  # Format: {app: foo}


class BlockTrafficType(BaseParameter):
    krknhub_name: str = "BLOCK_TRAFFIC_TYPE"
    krknctl_name: str = "block-traffic-type"
    value: str = "[Ingress, Egress]"  # "[Ingress, Egress]", "[Ingress]", "[Egress]"


class LabelSelectorParameter(BaseParameter):
    krknhub_name: str = "LABEL_SELECTOR"
    krknctl_name: str = "label-selector"
    value: str = ""  # Example Value: k8s-app=etcd


class ContainerNameParameter(BaseParameter):
    krknhub_name: str = "CONTAINER_NAME"
    krknctl_name: str = "container-name"
    value: str = ""  # Example Value: etcd


class ActionParameter(BaseParameter):
    krknhub_name: str = "ACTION"
    krknctl_name: str = "action"
    value: str = "1"
    # possible_values = ["1", "9"]


class TotalChaosDurationParameter(BaseParameter):
    krknhub_name: str = "TOTAL_CHAOS_DURATION"
    krknctl_name: str = "chaos-duration"
    value: int = 60


class NodeCPUCoreParameter(BaseParameter):
    krknhub_name: str = "NODE_CPU_CORE"
    krknctl_name: str = "cores"
    value: float = 2


class NodeCPUPercentageParameter(BaseParameter):
    """
    CPU usage percentage of the node cpu hog scenario between 20 and 100.
    """

    krknhub_name: str = "NODE_CPU_PERCENTAGE"
    krknctl_name: str = "cpu-percentage"
    value: int = 50

    def mutate(self):
        if rng.random() < 0.5:
            self.value += rng.randint(1, 35) * self.value / 100
        else:
            self.value -= rng.randint(1, 25) * self.value / 100
        self.value = int(self.value)
        self.value = max(self.value, 20)
        self.value = min(self.value, 100)


class NodeMemoryPercentageParameter(BaseParameter):
    """
    Memory usage percentage of the node memory hog scenario between 20 and 100.
    """

    krknhub_name: str = "MEMORY_CONSUMPTION_PERCENTAGE"
    krknctl_name: str = "memory-consumption"
    value: int = 50

    def get_value(self):
        return f"{self.value}%"

    def mutate(self):
        if rng.random() < 0.5:
            self.value += rng.randint(1, 35) * self.value / 100
        else:
            self.value -= rng.randint(1, 25) * self.value / 100
        self.value = int(self.value)
        self.value = max(self.value, 20)
        self.value = min(self.value, 100)


class NumberOfWorkersParameter(BaseParameter):
    krknhub_name: str = "NUMBER_OF_WORKERS"
    krknctl_name: str = "memory-workers"
    value: int = 1

    def mutate(self):
        self.value = rng.randint(1, 10)


class NodeSelectorParameter(BaseParameter):
    """
    CPU-Hog:
    Node selector where the scenario containers will be scheduled in the format “=<selector>”.
    NOTE: Will be instantiated a container per each node selected with the same scenario options.
    If left empty a random node will be selected

    Memory-Hog:
    defines the node selector for choosing target nodes. If not specified, one schedulable node in the cluster will be chosen at random. If multiple nodes match the selector, all of them will be subjected to stress. If number-of-nodes is specified, that many nodes will be randomly selected from those identified by the selector.
    """

    krknhub_name: str = "NODE_SELECTOR"
    krknctl_name: str = "node-selector"
    value: str = ""


class TaintParameter(BaseParameter):
    krknhub_name: str = "TAINTS"
    krknctl_name: str = "taints"
    value: str = "[]"


class NumberOfNodesParameter(BaseParameter):
    krknhub_name: str = "NUMBER_OF_NODES"
    krknctl_name: str = "number-of-nodes"
    value: int = 1


class HogScenarioImageParameter(BaseParameter):
    krknhub_name: str = "IMAGE"
    krknctl_name: str = "image"
    value: str = "quay.io/krkn-chaos/krkn-hog"


class ObjectTypeParameter(BaseParameter):
    krknhub_name: str = "OBJECT_TYPE"
    krknctl_name: str = "object-type"
    value: str = ""  # Available Types: pod, node

    def mutate(self):
        self.value = rng.choice(["pod", "node"])


class ActionTimeParameter(BaseParameter):
    krknhub_name: str = "ACTION"
    krknctl_name: str = "action"
    value: str = "skew_date"  # Available Types: skew_date, skew_time

    def mutate(self):
        self.value = rng.choice(["skew_date", "skew_time"])


class NetworkScenarioTypeParameter(BaseParameter):
    krknhub_name: str = "NETWORK_SCENARIO_TYPE"
    krknctl_name: str = "traffic-type"
    value: str = "ingress"

    def mutate(self):
        self.value = rng.choice(["ingress", "egress"])


class NetworkScenarioImageParameter(BaseParameter):
    krknhub_name: str = "IMAGE"
    krknctl_name: str = "image"
    value: str = "quay.io/krkn-chaos/krkn:tools"


class StandardDurationParameter(BaseParameter):
    """
    Standard duration parameter with krknctl_name="duration" and krknhub_name="DURATION".
    """

    krknhub_name: str = "DURATION"
    krknctl_name: str = "duration"
    value: int = 120


class NetworkScenarioLabelSelectorParameter(BaseParameter):
    krknhub_name: str = "LABEL_SELECTOR"
    krknctl_name: str = "label-selector"
    value: str = ""


class NetworkScenarioExecutionParameter(BaseParameter):
    krknhub_name: str = "EXECUTION"
    krknctl_name: str = "execution"
    value: str = "parallel"

    def mutate(self):
        self.value = rng.choice(["serial", "parallel"])


class NetworkScenarioNodeNameParameter(BaseParameter):
    krknhub_name: str = "NODE_NAME"
    krknctl_name: str = "node-name"
    value: str = ""


class NetworkScenarioInterfacesParameter(BaseParameter):
    # TODO: Understand the format and values of the interfaces parameter
    krknhub_name: str = "INTERFACES"
    krknctl_name: str = "interfaces"
    value: str = "[]"


class NetworkParamData(BaseModel):
    latency: int = 50  # ms
    loss: float = 0.02  # %
    bandwidth: int = 100  # mbit


class NetworkScenarioNetworkParamsParameter(BaseParameter):
    krknhub_name: str = "NETWORK_PARAMS"
    krknctl_name: str = "network-params"
    value: NetworkParamData = Field(default_factory=NetworkParamData)

    def mutate(self):
        self.value.latency = rng.randint(1, 1000)
        self.value.loss = round(rng.uniform(0.01, 0.1), 2)
        self.value.bandwidth = rng.randint(100, 1000)

    def get_value(self):
        return (
            "{"
            + f"latency: {self.value.latency}ms,loss: {self.value.loss},bandwidth: {self.value.bandwidth}mbit"
            + "}"
        )


class NetworkScenarioEgressParamsParameter(BaseParameter):
    krknhub_name: str = "EGRESS"
    krknctl_name: str = "egress"
    value: NetworkParamData = Field(default_factory=NetworkParamData)

    def mutate(self):
        self.value.latency = rng.randint(1, 1000)
        self.value.loss = round(rng.uniform(0.01, 0.1), 2)
        self.value.bandwidth = rng.randint(100, 1000)

    def get_value(self):
        return (
            "{"
            + f"latency: {self.value.latency}ms,loss: {self.value.loss},bandwidth: {self.value.bandwidth}mbit"
            + "}"
        )


class NetworkScenarioTargetNodeInterfaceParameter(BaseParameter):
    # TODO: Understand the format and values of the target-node-interface parameter
    krknhub_name: str = "TARGET_NODE_AND_INTERFACE"
    krknctl_name: str = "target-node-interface"
    value: str = "{}"


class DNSOutageDurationParameter(BaseParameter):
    krknhub_name: str = "TEST_DURATION"
    krknctl_name: str = "chaos-duration"
    value: int = 60


class DNSOutageProtocolParameter(BaseParameter):
    krknhub_name: str = "PROTOCOLS"
    krknctl_name: str = "protocols"
    value: str = "tcp,udp"


class DNSPortParameter(BaseParameter):
    krknhub_name: str = "PORTS"
    krknctl_name: str = "ports"
    value: str = ""


class PodNameParameter(BaseParameter):
    krknhub_name: str = "POD_NAME"
    krknctl_name: str = "pod-name"
    value: str = ""
    _namespace: str = PrivateAttr(default="")
    _owner_kind: Optional[str] = PrivateAttr(default=None)
    _owner_name: Optional[str] = PrivateAttr(default=None)

    def set_pod(self, namespace, pod):
        """Store pod identity for lazy resolution at execution time."""
        self.value = pod.name
        self._namespace = namespace
        if pod.owner:
            self._owner_kind = pod.owner.kind
            self._owner_name = pod.owner.name
        else:
            self._owner_kind = None
            self._owner_name = None

    def get_value(self):
        if self._namespace and self._owner_kind and self._owner_name:
            from krkn_ai.utils.pvc_utils import resolve_pod_name

            return resolve_pod_name(
                self._namespace, self.value, self._owner_kind, self._owner_name
            )
        return self.value


class IngressParameter(BaseParameter):
    krknhub_name: str = "INGRESS"
    krknctl_name: str = "ingress"
    value: str = "false"


class EgressParameter(BaseParameter):
    krknhub_name: str = "EGRESS"
    krknctl_name: str = "egress"
    value: str = "true"


# PVC Scenario Parameters
class PVCNameParameter(BaseParameter):
    krknhub_name: str = "PVC_NAME"
    krknctl_name: str = "pvc-name"
    value: str = ""


class FillPercentageParameter(BaseParameter):
    krknhub_name: str = "FILL_PERCENTAGE"
    krknctl_name: str = "fill-percentage"
    value: int = 50

    def mutate(self, min_value: float = None):
        """
        Mutate the fill percentage value.
        Args:
            min_value: Minimum value (e.g., current usage percentage). If provided, ensures value > min_value.
        """
        # Calculate valid range
        min_value_int = 1
        if min_value is not None:
            min_value_int = min(math.ceil(min_value) + 1, 99)

        # Random value between min_value_int and 99
        self.value = rng.randint(min_value_int, 99)


# SYN Flood Scenario Parameters
class SynFloodPacketSizeParameter(BaseParameter):
    krknhub_name: str = "PACKET_SIZE"
    krknctl_name: str = "packet-size"
    value: int = 120


class SynFloodWindowSizeParameter(BaseParameter):
    krknhub_name: str = "WINDOW_SIZE"
    krknctl_name: str = "window-size"
    value: int = 64


class SynFloodTargetServiceParameter(BaseParameter):
    krknhub_name: str = "TARGET_SERVICE"
    krknctl_name: str = "target-service"
    value: str = ""


class SynFloodTargetPortParameter(BaseParameter):
    krknhub_name: str = "TARGET_PORT"
    krknctl_name: str = "target-port"
    value: int = 80


class SynFloodTargetServiceLabelParameter(BaseParameter):
    krknhub_name: str = "TARGET_SERVICE_LABEL"
    krknctl_name: str = "target-service-label"
    value: str = ""


class SynFloodNumberOfPodsParameter(BaseParameter):
    krknhub_name: str = "NUMBER_OF_PODS"
    krknctl_name: str = "number-of-pods"
    value: int = 2


class SynFloodImageParameter(BaseParameter):
    krknhub_name: str = "IMAGE"
    krknctl_name: str = "image"
    value: str = "quay.io/krkn-chaos/krkn-syn-flood:latest"


class SynFloodNodeSelectorsParameter(BaseParameter):
    krknhub_name: str = "NODE_SELECTORS"
    krknctl_name: str = "node-selectors"
    value: str = ""


class IOBlockSizeParameter(BaseParameter):
    """
    Size of each write in bytes. Size can be from 1 byte to 4 Megabytes (allowed suffix are b,k,m)
    """

    krknhub_name: str = "IO_BLOCK_SIZE"
    krknctl_name: str = "io-block-size"
    value: int = 1048576  # 1MB in bytes (1024 * 1024)

    def get_value(self):
        """
        Format the value with appropriate unit suffix (b, k, m).
        Returns string like "1m", "512k", "1024b"
        """
        if self.value < 1024:
            return f"{self.value}b"
        elif self.value < 1024 * 1024:
            return f"{self.value // 1024}k"
        else:
            return f"{self.value // (1024 * 1024)}m"

    def mutate(self):
        """
        Randomly sample a value between 1 byte and 4MB (4194304 bytes).
        """
        # 4MB = 4 * 1024 * 1024 = 4194304 bytes
        max_bytes = 4 * 1024 * 1024
        self.value = rng.randint(1, max_bytes)


class IOWorkersParameter(BaseParameter):
    """
    Number of stressor instances
    """

    krknhub_name: str = "IO_WORKERS"
    krknctl_name: str = "io-workers"
    value: int = 5

    def mutate(self):
        self.value = rng.randint(1, 10)


class IOWriteBytesParameter(BaseParameter):
    """
    writes N bytes for each hdd process. The size can be expressed as % of free space on the file system
    or in units of Bytes, KBytes, MBytes and GBytes using the suffix b, k, m or g
    """

    krknhub_name: str = "IO_WRITE_BYTES"
    krknctl_name: str = "io-write-bytes"
    value: int = 10  # Percentage of free space (1-100)

    def get_value(self):
        return f"{self.value}%"

    def mutate(self):
        """
        Mutate the percentage value between 1 and 100.
        """
        if rng.random() < 0.5:
            self.value += rng.randint(1, 35) * self.value / 100
        else:
            self.value -= rng.randint(1, 25) * self.value / 100
        self.value = int(self.value)
        self.value = max(self.value, 1)
        self.value = min(self.value, 100)


class NodeMountPathParameter(BaseParameter):
    """
    the path in the node that will be mounted in the pod and where the io hog will be executed.
    NOTE: be sure that kubelet has the rights to write in that node path
    """

    krknhub_name: str = "NODE_MOUNT_PATH"
    krknctl_name: str = "node-mount-path"
    value: str = "/root"


class VMTimeoutParameter(BaseParameter):
    krknhub_name: str = "TIMEOUT"
    krknctl_name: str = "timeout"
    value: int = 60


class VMNameParameter(BaseParameter):
    krknhub_name: str = "VM_NAME"
    krknctl_name: str = "vm-name"
    value: str = ""


class KillCountParameter(BaseParameter):
    krknhub_name: str = "KILL_COUNT"
    krknctl_name: str = "kill-count"
    value: int = 1
