from collections import Counter

from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import *


class NodeCPUHogScenario(Scenario):
    name: str = "node-cpu-hog"
    chaos_duration: TotalChaosDurationParameter = TotalChaosDurationParameter()
    # node_cpu_core: NodeCPUCoreParameter = NodeCPUCoreParameter()
    node_cpu_percentage: NodeCPUPercentageParameter = NodeCPUPercentageParameter()
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
            self.node_selector,
            self.taint,
            self.number_of_nodes,
            self.hog_scenario_image,
        ]

    def mutate(self):
        nodes = self._cluster_components.nodes

        # scenario 1: Select a random node
        if rng.random() < 0.5:
            node = rng.choice(nodes)
            self.node_selector.value = f"kubernetes.io/hostname={node.name}"
            self.number_of_nodes.value = 1
            # self.node_cpu_core.value = node.free_cpu * 0.001  # convert to cores from millicores
        else:
            # scenario 2: Select a label
            all_labels = Counter()
            for node in nodes:
                for label, value in node.labels.items():
                    all_labels[f"{label}={value}"] += 1
            label = rng.choice(list(all_labels.keys()))
            self.node_selector.value = label
            self.number_of_nodes.value = rng.randint(1, all_labels[label])

            # get the minimum free cpu core for the selected label
            # min_cpu_core_milli = float('inf')
            # for node in nodes:
            #     if label in node.labels and node.labels[label] == label.split("=")[1]:
            #         min_cpu_core_milli = min(min_cpu_core_milli, node.free_cpu)
            # if min_cpu_core_milli == float('inf'):
            #     min_cpu_core_milli = 2000 # 2000m CPU
            # self.node_cpu_core.value = min_cpu_core_milli * 0.001  # convert to cores from millicores

        self.node_cpu_percentage.mutate()
