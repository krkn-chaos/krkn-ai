from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import *


class PodScenario(Scenario):
    name: str = "pod-scenarios"
    namespace: NamespaceParameter = NamespaceParameter()
    pod_label: PodLabelParameter = PodLabelParameter()
    name_pattern: NamePatternParameter = NamePatternParameter()
    disruption_count: DisruptionCountParameter = DisruptionCountParameter()
    kill_timeout: KillTimeoutParameter = KillTimeoutParameter()
    exp_recovery_time: ExpRecoveryTimeParameter = ExpRecoveryTimeParameter()

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        return [
            self.namespace,
            self.pod_label,
            self.name_pattern,
            self.disruption_count,
            self.kill_timeout,
            self.exp_recovery_time,
        ]

    def mutate(self):
        namespace = rng.choice(self._cluster_components.namespaces)
        pod = rng.choice(namespace.pods)
        labels = pod.labels
        label = rng.choice(list(labels.keys()))

        self.namespace.value = namespace.name

        # pod_label is a string of the form "key=value"
        self.pod_label.value = "{}={}".format(label, labels[label])

