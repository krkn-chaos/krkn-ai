from collections import defaultdict
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import *


class DnsOutageScenario(Scenario):
    name: str = "dns-outage"
    krknctl_name: str = "pod-network-filter"
    krknhub_image: str = "quay.io/krkn-chaos/krkn-hub:pod-network-filter"

    duration: DNSOutageDurationParameter = DNSOutageDurationParameter()
    namespace: NamespaceParameter = NamespaceParameter()
    pod_name: PodNameParameter = PodNameParameter()
    ingress: IngressParameter = IngressParameter(value="false")
    egress: EgressParameter = EgressParameter(value="true")
    protocol: DNSOutageProtocolParameter = DNSOutageProtocolParameter()
    ports: DNSPortParameter = DNSPortParameter(value="53")

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        return [
            self.duration,
            self.pod_name,
            self.namespace,
            self.ingress,
            self.egress,
            self.protocol,
            self.ports,
        ]

    def mutate(self):
        # Select a random pod from all pods in the cluster
        pods = [
            (ns, pod) for ns in self._cluster_components.namespaces for pod in ns.pods
        ]
        ns, pod = rng.choice(pods)
        self.namespace.value = ns.name
        self.pod_name.value = pod.name
