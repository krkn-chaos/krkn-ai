from chaos_ai.models.scenario.base import BaseParameter

class DummyParameter(BaseParameter):
    name: str
    value: int


class NamespaceParameter(BaseParameter):
    name: str = "NAMESPACE"
    value: str = ""


class PodLabelParameter(BaseParameter):
    name: str = "POD_LABEL"
    value: str = ""  # Example: service=payment


class NamePatternParameter(BaseParameter):
    name: str = "NAME_PATTERN"
    value: str = ".*"


class DisruptionCountParameter(BaseParameter):
    name: str = "DISRUPTION_COUNT"
    value: int = 1


class KillTimeoutParameter(BaseParameter):
    name: str = "KILL_TIMEOUT"
    value: int = 60


class ExpRecoveryTimeParameter(BaseParameter):
    name: str = "EXPECTED_RECOVERY_TIME"
    value: int = 60



class DurationParameter(BaseParameter):
    name: str = "DURATION"
    value: int = 60



class PodSelectorParameter(BaseParameter):
    name: str = "POD_SELECTOR"
    value: str = "" # Format: {app: foo}


class BlockTrafficType(BaseParameter):
    name: str = "BLOCK_TRAFFIC_TYPE"
    value: str = "[Ingress, Egress]" # "[Ingress, Egress]", "[Ingress]", "[Egress]"


class LabelSelectorParameter(BaseParameter):
    name: str = "LABEL_SELECTOR"
    value: str  # Example Value: k8s-app=etcd


class ContainerNameParameter(BaseParameter):
    name: str = "CONTAINER_NAME"
    value: str  # Example Value: etcd

class ActionParameter(BaseParameter):
    name: str = "ACTION"
    value: str = "1"
    # possible_values = ["1", "9"]


class TotalChaosDurationParameter(BaseParameter):
    name: str = "TOTAL_CHAOS_DURATION"
    value: int = 60


class NodeCPUCoreParameter(BaseParameter):
    name: str = "NODE_CPU_CORE"
    value: int = 2


class NodeCPUPercentageParameter(BaseParameter):
    name: str = "NODE_CPU_PERCENTAGE"
    value: int = 50


class NodeMemopryPercentageParameter(BaseParameter):
    name: str = "MEMORY_CONSUMPTION_PERCENTAGE"
    value: int = 90

    def get_value(self):
        return f"{self.value}%"


class NumberOfWorkersParameter(BaseParameter):
    name: str = "NUMBER_OF_WORKERS"
    value: int = 1


class NodeSelectorParameter(BaseParameter):
    name: str = "NODE_SELECTOR"
    value: str = ""


class TaintParameter(BaseParameter):
    name: str = "TAINTS"
    value: str = '[]'


class NumberOfNodesParameter(BaseParameter):
    name: str = "NUMBER_OF_NODES"
    value: int = 1


class HogScenarioImageParameter(BaseParameter):
    name: str = "IMAGE"
    value: str = "quay.io/krkn-chaos/krkn-hog"
