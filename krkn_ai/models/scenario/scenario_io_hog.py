from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    HogScenarioImageParameter,
    IOBlockSizeParameter,
    IOWorkersParameter,
    IOWriteBytesParameter,
    NamespaceParameter,
    NodeMountPathParameter,
    NodeSelectorParameter,
    NumberOfNodesParameter,
    TaintParameter,
    TotalChaosDurationParameter,
)
from krkn_ai.utils.node_selector import select_nodes


class NodeIOHogScenario(Scenario):
    name: str = "node-io-hog"
    krknctl_name: str = "node-io-hog"
    krknhub_image: str = "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:node-io-hog"

    chaos_duration: TotalChaosDurationParameter = TotalChaosDurationParameter()
    io_block_size: IOBlockSizeParameter = IOBlockSizeParameter()
    io_workers: IOWorkersParameter = IOWorkersParameter()
    io_write_bytes: IOWriteBytesParameter = IOWriteBytesParameter()
    node_mount_path: NodeMountPathParameter = NodeMountPathParameter()
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
            self.io_block_size,
            self.io_workers,
            self.io_write_bytes,
            self.node_mount_path,
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

        self.io_workers.mutate()
        self.io_write_bytes.mutate()
        self.io_block_size.mutate()
