from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    NamespaceParameter,
    LabelSelectorParameter,
    PodNameParameter,
    PodNetworkChaosImageParameter,
    ExcludeLabelParameter,
    InstanceCountParameter,
    PodNetworkTrafficTypeParameter,
    IngressPortsParameter,
    EgressPortsParameter,
    TestDurationParameter,
    PodNetworkWaitDurationParameter,
)


class PodNetworkScenario(Scenario):
    name: str = "pod-network-chaos"
    krknctl_name: str = "pod-network-chaos"
    krknhub_image: str = (
        "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:pod-network-chaos"
    )

    namespace: NamespaceParameter = NamespaceParameter()
    image: PodNetworkChaosImageParameter = PodNetworkChaosImageParameter()
    label_selector: LabelSelectorParameter = LabelSelectorParameter()
    exclude_label: ExcludeLabelParameter = ExcludeLabelParameter()
    pod_name: PodNameParameter = PodNameParameter()
    instance_count: InstanceCountParameter = InstanceCountParameter()
    traffic_type: PodNetworkTrafficTypeParameter = PodNetworkTrafficTypeParameter()
    ingress_ports: IngressPortsParameter = IngressPortsParameter()
    egress_ports: EgressPortsParameter = EgressPortsParameter()
    wait_duration: PodNetworkWaitDurationParameter = PodNetworkWaitDurationParameter()
    test_duration: TestDurationParameter = TestDurationParameter()

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        return [
            self.namespace,
            self.image,
            self.label_selector,
            self.exclude_label,
            self.pod_name,
            self.instance_count,
            self.traffic_type,
            self.ingress_ports,
            self.egress_ports,
            self.wait_duration,
            self.test_duration,
        ]

    def mutate(self):
        namespaces_with_pods = [
            ns for ns in self._cluster_components.namespaces if len(ns.pods) > 0
        ]
        if len(namespaces_with_pods) == 0:
            raise ScenarioParameterInitError("No pods found in cluster components")

        namespace = rng.choice(namespaces_with_pods)
        self.namespace.value = namespace.name

        pods = namespace.pods
        selected_pod = rng.choice(pods)

        use_label_selector = rng.choice([True, False])

        if use_label_selector and len(selected_pod.labels) > 0:
            label_key = rng.choice(list(selected_pod.labels.keys()))
            label_value = selected_pod.labels[label_key]
            self.label_selector.value = f"{label_key}={label_value}"
            self.pod_name.value = ""

            # Check if there are other pods to potentially exclude
            other_labels = set()
            for p in pods:
                if p.name != selected_pod.name:
                    for k, v in p.labels.items():
                        other_labels.add(f"{k}={v}")

            if other_labels and rng.choice([True, False]):
                self.exclude_label.value = rng.choice(list(other_labels))
            else:
                self.exclude_label.value = ""
        else:
            self.pod_name.set_pod(namespace.name, selected_pod)
            self.label_selector.value = ""
            self.exclude_label.value = ""

        self.instance_count.mutate()
        self.traffic_type.mutate()

        # Mutate port filters
        if rng.choice([True, False]):
            self.ingress_ports.value = rng.choice(["[80]", "[443]", "[80,443]", ""])
        else:
            self.ingress_ports.value = ""

        if rng.choice([True, False]):
            self.egress_ports.value = rng.choice(["[80]", "[443]", "[80,443]", ""])
        else:
            self.egress_ports.value = ""

        self.test_duration.mutate()
        # Enforce wait-duration is at least 2 * test-duration
        self.wait_duration.value = self.test_duration.value * 2 + rng.choice([0, 30, 60])
