from typing import List, Tuple
from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    DisruptionCountParameter,
    ExpRecoveryTimeParameter,
    KillTimeoutParameter,
    NamePatternParameter,
    NamespaceParameter,
    PodLabelParameter,
)
from krkn_ai.models.cluster_components import Namespace, Pod


class PodScenario(Scenario):
    name: str = "pod-scenarios"
    krknctl_name: str = "pod-scenarios"
    krknhub_image: str = "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:pod-scenarios"
    crossover_parameter_groups = ((NamespaceParameter, PodLabelParameter),)

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
        namespace_pod_tuple: List[Tuple[Namespace, Pod]] = []

        # look for pods with labels
        for namespace in self._cluster_components.namespaces:
            for pod in namespace.pods:
                if len(pod.labels) > 0:
                    namespace_pod_tuple.append((namespace, pod))

        if len(namespace_pod_tuple) == 0:
            raise ScenarioParameterInitError(
                "No pods found with labels for pod scenario"
            )

        # Select a random namespace and pod from the tuple list
        namespace, pod = rng.choice(namespace_pod_tuple)
        labels = pod.labels
        label = rng.choice(list(labels.keys()))

        # Update parameter values
        self.namespace.value = namespace.name

        # pod_label is a string of the form "key=value"
        self.pod_label.value = "{}={}".format(label, labels[label])
