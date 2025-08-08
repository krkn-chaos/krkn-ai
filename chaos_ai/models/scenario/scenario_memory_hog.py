import random

from chaos_ai.models.scenario.base import Scenario
from chaos_ai.models.scenario.parameters import *


class NodeMemoryHogScenario(Scenario):
    name: str = "node-memory-hog"
    chaos_duration: TotalChaosDurationParameter = TotalChaosDurationParameter()
    node_memory_percentage: NodeMemoryPercentageParameter = NodeMemoryPercentageParameter()
    number_of_workers: NumberOfWorkersParameter = NumberOfWorkersParameter()
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
            self.node_selector,
            self.taint,
            self.number_of_nodes,
            self.hog_scenario_image,
        ]

    def mutate(self):
        # TODO: Get node info from cluster

        # for node_selector, need to find what labels are there to all nodes

        # for number_of_nodes, check how many nodes are there for given node_selector then that would be the max value for that parameter and randomize

        self.node_memory_percentage.mutate()

