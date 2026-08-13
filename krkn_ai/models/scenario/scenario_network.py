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


_INGRESS_WAIT_DURATION = (
    30  # krkn requires >= 1 for ingress; 300s is krkn's own default
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
        common = [
            self.traffic_type,
            self.image,
            self.duration,
            self.label_selector,
            self.execution,
        ]
        if self.traffic_type.value == "ingress":
            return common + [
                self.network_params,
                self.target_node_interface,
            ]
        # egress
        return common + [
            self.node_name,
            self.egress_params,
        ]

    def scenario_wait_duration(self, config_wait_duration: int) -> int:
        if self.traffic_type.value == "ingress":
            return max(config_wait_duration, _INGRESS_WAIT_DURATION)
        return config_wait_duration

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

        node = rng.choice(nodes)
        self.node_name.value = node.name
        self.interfaces.value = f"[{rng.choice(node.interfaces)}]"

        if self.traffic_type.value == "ingress":
            self.network_params.mutate()
            self.target_node_interface.value = (
                "{" + f"{node.name}: [{rng.choice(node.interfaces)}]" + "}"
            )
        elif self.traffic_type.value == "egress":
            self.egress_params.mutate()
