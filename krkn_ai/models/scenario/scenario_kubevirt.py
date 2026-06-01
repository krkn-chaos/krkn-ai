from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    KillCountParameter,
    NamespaceParameter,
    VMNameParameter,
    VMTimeoutParameter,
)
from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.models.cluster_components import Namespace, VMI
from typing import List, Tuple


class KubevirtDisruptionScenario(Scenario):
    name: str = "kubevirt-outage"
    krknctl_name: str = "kubevirt-outage"
    krknhub_image: str = "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:kubevirt-outage"

    timeout: VMTimeoutParameter = VMTimeoutParameter()
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
        if len(self._cluster_components.namespaces) == 0:
            raise ScenarioParameterInitError(
                "No namespaces found in cluster components"
            )

        namespaces: List[Tuple[Namespace, VMI]] = []  # (namespace, vm)

        for ns in self._cluster_components.namespaces:
            if len(ns.vmis) > 0:
                namespaces.extend((ns, vmi) for vmi in ns.vmis)

        # Check availability before mutation - skip test if no vms found
        if not namespaces:
            raise ScenarioParameterInitError(
                "No VMS found in cluster components for KubeVirt scenario"
            )

        namespace, vmi = rng.choice(namespaces)
        self.vm_name.value = vmi.name
        self.namespace.value = namespace.name
        self.kill_count.value = 1  # Set to 1 as we select only one VM by name
