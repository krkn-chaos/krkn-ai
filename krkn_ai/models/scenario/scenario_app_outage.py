from typing import List, Tuple
from krkn_ai.models.cluster_components import Namespace, Pod
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    BlockTrafficType,
    DurationParameter,
    NamespaceParameter,
    PodSelectorParameter,
)
from krkn_ai.models.custom_errors import ScenarioParameterInitError


class AppOutageScenario(Scenario):
    name: str = "application-outages"
    krknctl_name: str = "application-outages"
    krknhub_image: str = (
        "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:application-outages"
    )
    crossover_parameter_groups = ((NamespaceParameter, PodSelectorParameter),)

    namespace: NamespaceParameter = NamespaceParameter()
    duration: DurationParameter = DurationParameter()
    pod_selector: PodSelectorParameter = PodSelectorParameter()
    block_traffic_type: BlockTrafficType = BlockTrafficType()

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        return [
            self.namespace,
            self.duration,
            self.pod_selector,
            self.block_traffic_type,
        ]

    def mutate(self):
        namespace_pod_tuple: List[Tuple[Namespace, Pod]] = []

        # look for pods with labels
        for namespace in self._cluster_components.namespaces:
            for pod in namespace.pods:
                if len(pod.labels) > 0:
                    namespace_pod_tuple.append((namespace, pod))

        if len(namespace_pod_tuple) == 0:
            raise ScenarioParameterInitError(
                "No pods found with labels for application outage scenario"
            )

        # Select a random namespace and pod from the tuple list
        namespace, pod = rng.choice(namespace_pod_tuple)
        labels = pod.labels
        label = rng.choice(list(labels.keys()))

        # Update parameter values
        self.namespace.value = namespace.name

        # pod_selector is a string of the form "{app: foo}"
        self.pod_selector.value = f"{{{label}: {labels[label]}}}"

        self.block_traffic_type.value = rng.choice(
            ["[Ingress, Egress]", "[Ingress]", "[Egress]"]
        )
