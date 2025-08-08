import random

from chaos_ai.models.scenario.base import Scenario
from chaos_ai.models.scenario.parameters import *


class NodeCPUHogScenario(Scenario):
    name: str = "node-cpu-hog"
    chaos_duration: TotalChaosDurationParameter = TotalChaosDurationParameter()
    node_cpu_core: NodeCPUCoreParameter = NodeCPUCoreParameter()
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
            self.node_cpu_core,
            self.node_cpu_percentage,
            self.node_selector,
            self.taint,
            self.number_of_nodes,
            self.hog_scenario_image,
        ]

    def mutate(self):
        # TODO: Get node info from cluster, Use that to update cpu_core and percentage

        # for node_selector, need to find what labels are there to all nodes

        # for number_of_nodes, check how many nodes are there for given node_selector then that would be the max value for that parameter and randomize

        self.node_cpu_percentage.mutate()

