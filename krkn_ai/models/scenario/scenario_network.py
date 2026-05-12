from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    NetworkScenarioEgressParamsParameter,
    NetworkScenarioExecutionParameter,
    NetworkScenarioImageParameter,
    NetworkScenarioInterfacesParameter,
    NetworkScenarioLabelSelectorParameter,
    NetworkScenarioNetworkParamsParameter,
    NetworkScenarioNodeNameParameter,
    NetworkScenarioTargetNodeInterfaceParameter,
    NetworkScenarioTypeParameter,
    StandardDurationParameter,
)


class NetworkScenario(Scenario):
    name: str = "network-chaos"
    krknctl_name: str = "network-chaos"
    krknhub_image: str = "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:network-chaos"

    traffic_type: NetworkScenarioTypeParameter = NetworkScenarioTypeParameter()
    image: NetworkScenarioImageParameter = NetworkScenarioImageParameter()
    duration: StandardDurationParameter = StandardDurationParameter()
    label_selector: NetworkScenarioLabelSelectorParameter = (
        NetworkScenarioLabelSelectorParameter()
    )
    execution: NetworkScenarioExecutionParameter = NetworkScenarioExecutionParameter()
    node_name: NetworkScenarioNodeNameParameter = NetworkScenarioNodeNameParameter()
    interfaces: NetworkScenarioInterfacesParameter = (
        NetworkScenarioInterfacesParameter()
    )
    network_params: NetworkScenarioNetworkParamsParameter = (
        NetworkScenarioNetworkParamsParameter()
    )
    egress_params: NetworkScenarioEgressParamsParameter = (
        NetworkScenarioEgressParamsParameter()
    )
    target_node_interface: NetworkScenarioTargetNodeInterfaceParameter = (
        NetworkScenarioTargetNodeInterfaceParameter()
    )

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
        ]

    def mutate(self):
        # Get nodes with interfaces
        nodes = [
            node for node in self._cluster_components.nodes if len(node.interfaces) > 0
        ]

        if len(nodes) == 0:
            raise ScenarioParameterInitError(
                "No nodes found with interfaces in cluster components"
            )

        self.traffic_type.mutate()
        self.execution.mutate()

        if self.traffic_type.value == "ingress":
            self.network_params.mutate()
        elif self.traffic_type.value == "egress":
            self.egress_params.mutate()

        node = rng.choice(nodes)
        self.node_name.value = node.name
        self.interfaces.value = f"[{rng.choice(node.interfaces)}]"
        self.target_node_interface.value = (
            "{" + f"{node.name}: [{rng.choice(node.interfaces)}]" + " }"
        )
