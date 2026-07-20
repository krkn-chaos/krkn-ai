from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.cluster import select_nodes
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    HogScenarioImageParameter,
    NamespaceParameter,
    NodeMemoryPercentageParameter,
    NodeSelectorParameter,
    NumberOfNodesParameter,
    NumberOfWorkersParameter,
    TaintParameter,
    TotalChaosDurationParameter,
)


class NodeMemoryHogScenario(Scenario):
    name: str = "node-memory-hog"
    krknctl_name: str = "node-memory-hog"
    krknhub_image: str = "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:node-memory-hog"

    chaos_duration: TotalChaosDurationParameter = TotalChaosDurationParameter()
    node_memory_percentage: NodeMemoryPercentageParameter = (
        NodeMemoryPercentageParameter()
    )
    number_of_workers: NumberOfWorkersParameter = NumberOfWorkersParameter()
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
            self.node_memory_percentage,
            self.number_of_workers,
            self.namespace,
            self.node_selector,
            self.taint,
            self.number_of_nodes,
            self.hog_scenario_image,
        ]

    def mutate(self):
        """Mutate memory hog scenario parameters by selecting target nodes."""
        nodes = self._cluster_components.nodes

        if not nodes:
            raise ScenarioParameterInitError(
                "No nodes found in cluster components for node-memory-hog scenario"
            )

        # Use shared node selection logic
        result = select_nodes(nodes)

        self.node_selector.value = result.node_selector
        self.number_of_nodes.value = result.number_of_nodes
        self.taint.value = result.taints_json

        self.number_of_workers.mutate()
        self.node_memory_percentage.mutate()
