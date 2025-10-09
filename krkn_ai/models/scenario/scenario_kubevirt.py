from collections import Counter

from chaos_ai.utils.rng import rng
from chaos_ai.models.scenario.base import Scenario
from chaos_ai.models.scenario.parameters import *


class KubevirtDisruptionScenario(Scenario):
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
            self.timeout,
            self.vm_name,
            self.namespace,
            self.kill_count,
        ]

    def mutate(self):
        namespace = rng.choice(self._cluster_components.namespaces)
        vms = rng.choice(namespace.vms)
        self.vm_name.value = vms.name
        self.namespace.value = namespace.name
        self.kill_count.mutate()

