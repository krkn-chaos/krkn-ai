from collections import Counter

from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import *


class KubevirtDisruptionScenario(Scenario):
    name: str = "kubevirt-outage"
    timeout: TimeoutParameter = TimeoutParameter()
    vm_name: VMNameParameter = VMNameParameter()
    namespace: NamespaceParameter = NamespaceParameter()
    kill_count: KillCountParameter = KillCountParameter()

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

