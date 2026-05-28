from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    ActionTimeParameter,
    ContainerNameParameter,
    LabelSelectorParameter,
    NamespaceParameter,
    ObjectTypeParameter,
)


class TimeScenario(Scenario):
    name: str = "time-scenarios"
    krknctl_name: str = "time-scenarios"
    krknhub_image: str = "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:time-scenarios"

    object_type: ObjectTypeParameter = ObjectTypeParameter()
    label_selector: LabelSelectorParameter = LabelSelectorParameter()
    action_time: ActionTimeParameter = ActionTimeParameter()
    container_name: ContainerNameParameter = ContainerNameParameter()
    namespace: NamespaceParameter = NamespaceParameter()

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        return [
            self.object_type,
            self.label_selector,
            self.action_time,
            self.container_name,
            self.namespace,
        ]

    def mutate(self):
        # Pre-check if data is available for scenario
        namespaces_with_pods = [
            namespace
            for namespace in self._cluster_components.namespaces
            if len(namespace.pods) > 0
        ]
        if not namespaces_with_pods:
            raise ScenarioParameterInitError(
                "No namespaces with pods found in cluster components"
            )
        namespace = rng.choice(namespaces_with_pods)
        all_pod_labels = set()
        for p in namespace.pods:
            for label, value in p.labels.items():
                all_pod_labels.add(f"{label}={value}")

        all_node_labels = set()
        for n in self._cluster_components.nodes:
            for label, value in n.labels.items():
                all_node_labels.add(f"{label}={value}")

        if len(all_pod_labels) == 0 and len(all_node_labels) == 0:
            raise ScenarioParameterInitError(
                "No labels found for pods and nodes in cluster components"
            )

        if len(all_node_labels) == 0:
            self.object_type.value = "pod"
        elif len(all_pod_labels) == 0:
            self.object_type.value = "node"
        else:
            self.object_type.mutate()

        self.action_time.mutate()

        # Select a random label from the available labels
        if self.object_type.value == "pod":
            self.label_selector.value = rng.choice(list(all_pod_labels))
            self.namespace.value = namespace.name
        else:
            self.label_selector.value = rng.choice(list(all_node_labels))
            self.namespace.value = ""
