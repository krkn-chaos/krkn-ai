from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import *


class AppOutageScenario(Scenario):
    name: str = "application-outages"
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
        namespace = rng.choice(self._cluster_components.namespaces)
        pod = rng.choice(namespace.pods)
        labels = pod.labels
        label = rng.choice(list(labels.keys()))

        self.namespace.value = namespace.name

        # pod_selector is a string of the form "{app: foo}"
        self.pod_selector.value = f"{{{label}: {labels[label]}}}"

        self.block_traffic_type.value = rng.choice(["[Ingress, Egress]", "[Ingress]", "[Egress]"])
