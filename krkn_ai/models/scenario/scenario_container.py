from typing import List, Tuple
from krkn_ai.models.cluster_components import Namespace, Pod
from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    ActionParameter,
    ContainerNameParameter,
    DisruptionCountParameter,
    ExpRecoveryTimeParameter,
    LabelSelectorParameter,
    NamespaceParameter,
)


class ContainerScenario(Scenario):
    name: str = "container-scenarios"
    krknctl_name: str = "container-scenarios"
    krknhub_image: str = (
        "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:container-scenarios"
    )

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
        namespace_pod_tuple: List[Tuple[Namespace, Pod]] = []

        # look for pods with labels and at least one container. A pod without
        # containers cannot be targeted by a container scenario and would make the
        # ``rng.randint(1, len(pod.containers))`` call below crash with
        # "ValueError: low >= high", terminating the whole GA run.
        for namespace in self._cluster_components.namespaces:
            for pod in namespace.pods:
                if len(pod.labels) > 0 and len(pod.containers) > 0:
                    namespace_pod_tuple.append((namespace, pod))

        if len(namespace_pod_tuple) == 0:
            raise ScenarioParameterInitError(
                "No pods found with labels and containers for container scenario"
            )

        # Select a random namespace and pod from the tuple list
        namespace, pod = rng.choice(namespace_pod_tuple)
        labels = pod.labels
        label = rng.choice(list(labels.keys()))

        self.namespace.value = namespace.name

        # pod_label is a string of the form "key=value"
        self.label_selector.value = "{}={}".format(label, labels[label])

        # CONTAINER_NAME selects which container(s) to kill inside each disrupted
        # pod: either one specific container, or ".*" to target every container.
        # It is chosen before the disruption count because it constrains which
        # pods can actually be targeted. (#277)
        if rng.random() < 0.5:
            self.container_name.value = rng.choice([x.name for x in pod.containers])
        else:
            self.container_name.value = ".*"

        target_container = self.container_name.value

        def is_targetable(candidate: Pod) -> bool:
            """Whether the label selector and container name both apply to a pod."""
            if candidate.labels.get(label) != labels[label]:
                return False
            if target_container == ".*":
                return len(candidate.containers) > 0
            return any(c.name == target_container for c in candidate.containers)

        # DISRUPTION_COUNT is the number of *pods* to disrupt, not the container
        # count of a single pod. Only pods that also contain the targeted
        # container are counted: pods sharing a generic label (e.g. env=prod) can
        # be completely different workloads, so counting them would let krkn pick
        # a pod that has no such container and fail the lookup. (#277)
        matching_pod_count = sum(1 for p in namespace.pods if is_targetable(p))
        self.disruption_count.value = rng.randint(1, matching_pod_count)

        self.action.value = rng.choice(["1", "9"])
