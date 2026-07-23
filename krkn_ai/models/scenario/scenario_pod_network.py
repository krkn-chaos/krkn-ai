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
        params = [self.namespace, self.image]
        if self.label_selector.value:
            params.append(self.label_selector)
            if self.exclude_label.value:
                params.append(self.exclude_label)
        elif self.pod_name.value:
            params.append(self.pod_name)

        params.extend([self.instance_count, self.traffic_type])

        if self.ingress_ports.value:
            params.append(self.ingress_ports)
        if self.egress_ports.value:
            params.append(self.egress_ports)

        params.extend([self.wait_duration, self.test_duration])
        return params

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
            self.pod_name.clear()

            # Check if there are other pods to potentially exclude
            other_labels = set()
            for p in pods:
                if p.name != selected_pod.name:
                    for k, v in p.labels.items():
                        # Do not exclude labels that selected_pod also carries
                        if k not in selected_pod.labels or selected_pod.labels[k] != v:
                            other_labels.add(f"{k}={v}")

            if other_labels and rng.choice([True, False]):
                # Sort the list conversion of the set to guarantee deterministic RNG selection across processes
                self.exclude_label.value = rng.choice(sorted(list(other_labels)))
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
