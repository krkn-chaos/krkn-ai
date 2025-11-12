from collections import defaultdict
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import *


class NetworkScenario(Scenario):
    name: str = "network-chaos"
    krknctl_name: str = "network-chaos"
    krknhub_image: str = "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:network-chaos"

    traffic_type: NetworkScenarioTypeParameter = NetworkScenarioTypeParameter()
    image: NetworkScenarioImageParameter = NetworkScenarioImageParameter()
    duration: NetworkScenarioDurationParameter = NetworkScenarioDurationParameter()
    label_selector: NetworkScenarioLabelSelectorParameter = NetworkScenarioLabelSelectorParameter()
    execution: NetworkScenarioExecutionParameter = NetworkScenarioExecutionParameter()
    node_name: NetworkScenarioNodeNameParameter = NetworkScenarioNodeNameParameter()
    interfaces: NetworkScenarioInterfacesParameter = NetworkScenarioInterfacesParameter()
    network_params: NetworkScenarioNetworkParamsParameter = NetworkScenarioNetworkParamsParameter()
    egress_params: NetworkScenarioEgressParamsParameter = NetworkScenarioEgressParamsParameter()
    target_node_interface: NetworkScenarioTargetNodeInterfaceParameter = NetworkScenarioTargetNodeInterfaceParameter()
    wait_duration: NetworkScenarioWaitDurationParameter = NetworkScenarioWaitDurationParameter()

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        return [
            self.traffic_type,
            self.image,
            self.duration,
            self.label_selector,
            self.execution,
            self.node_name,
            self.network_params,
            self.egress_params,
            # self.interfaces,
            self.target_node_interface,
            # self.wait_duration,
        ]

    def mutate(self):
        # TODO: Add support for ingress traffic type
        self.traffic_type.value = "egress"
        self.execution.mutate()

        if self.traffic_type.value == "ingress":
            self.network_params.mutate()
        elif self.traffic_type.value == "egress":
            self.egress_params.mutate()

        nodes = self._cluster_components.nodes

        node = rng.choice(nodes)        
        self.node_name.value = node.name
        self.interfaces.value = f"[{rng.choice(node.interfaces)}]"
        self.target_node_interface.value = "{" + f"{node.name}: [{rng.choice(node.interfaces)}]" + " }"
