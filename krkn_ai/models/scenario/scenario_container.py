from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import *


class ContainerScenario(Scenario):
    name: str = "container-scenarios"
    namespace: NamespaceParameter = NamespaceParameter()
    label_selector: LabelSelectorParameter = LabelSelectorParameter()
    disruption_count: DisruptionCountParameter = DisruptionCountParameter()
    container_name: ContainerNameParameter = ContainerNameParameter()
    action: ActionParameter = ActionParameter()
    exp_recovery_time: ExpRecoveryTimeParameter = ExpRecoveryTimeParameter()

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        return [
            self.namespace,
            self.label_selector,
            self.disruption_count,
            self.container_name,
            self.action,
            self.exp_recovery_time,
        ]

    def mutate(self):
        namespace = rng.choice(self._cluster_components.namespaces)
        pod = rng.choice(namespace.pods)
        labels = pod.labels
        label = rng.choice(list(labels.keys()))

        self.namespace.value = namespace.name

        # pod_label is a string of the form "key=value"
        self.label_selector.value = "{}={}".format(label, labels[label])

        self.disruption_count.value = rng.randint(1, len(pod.containers))

        if self.disruption_count.value == 1:
            # TODO: Verify whether we need to keep it empty or use regex pattern to match all container
            self.container_name.value = ".*"
        else:
            # Select specific container to kill in the pod
            self.container_name.value = rng.choice([x.name for x in pod.containers])

        self.action.value = rng.choice(["1", "9"])
