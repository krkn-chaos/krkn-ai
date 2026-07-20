from krkn_ai.cluster import select_nodes
from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    HogScenarioImageParameter,
    NodeCPUPercentageParameter,
    NamespaceParameter,
    NodeSelectorParameter,
    NumberOfNodesParameter,
    TaintParameter,
    TotalChaosDurationParameter,
)


class NodeCPUHogScenario(Scenario):
    name: str = "node-cpu-hog"
    krknctl_name: str = "node-cpu-hog"
    krknhub_image: str = "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:node-cpu-hog"

    chaos_duration: TotalChaosDurationParameter = TotalChaosDurationParameter()
    # node_cpu_core: NodeCPUCoreParameter = NodeCPUCoreParameter()
    node_cpu_percentage: NodeCPUPercentageParameter = NodeCPUPercentageParameter()
    namespace: NamespaceParameter = NamespaceParameter(value="default")
    node_selector: NodeSelectorParameter = NodeSelectorParameter()
    taint: TaintParameter = TaintParameter()
    number_of_nodes: NumberOfNodesParameter = NumberOfNodesParameter()
    hog_scenario_image: HogScenarioImageParameter = HogScenarioImageParameter()

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        return [
            self.chaos_duration,
            # self.node_cpu_core,
            self.node_cpu_percentage,
            self.namespace,
            self.node_selector,
            self.taint,
            self.number_of_nodes,
            self.hog_scenario_image,
        ]

    def mutate(self):
        """Mutate CPU hog scenario parameters by selecting target nodes."""
        nodes = self._cluster_components.nodes

        if not nodes:
            raise ScenarioParameterInitError(
                "No nodes found in cluster components for node-cpu-hog scenario"
            )

        # Use shared node selection logic
        result = select_nodes(nodes)

        self.node_selector.value = result.node_selector
        self.number_of_nodes.value = result.number_of_nodes
        self.taint.value = result.taints_json

        self.node_cpu_percentage.mutate()
