from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    HogScenarioImageParameter,
    NamespaceParameter,
    NodeCPUPercentageParameter,
    NodeSelectorParameter,
    NumberOfNodesParameter,
    TaintParameter,
    TotalChaosDurationParameter,
)
from krkn_ai.utils.node_selector import select_nodes


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
        """Mutate scenario parameters with random node selection."""
        nodes = self._cluster_components.nodes
        selection = select_nodes(nodes, scenario_name=self.name)

        self.node_selector.value = selection.node_selector
        self.number_of_nodes.value = selection.number_of_nodes
        self.taint.value = selection.taints_json

        self.node_cpu_percentage.mutate()
