from typing import List, Tuple
from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    MountPathParameter,
    NamespaceParameter,
    PodNameParameter,
    PVCNameParameter,
    ReadBPSParameter,
    ReadIOPSParameter,
    StandardDurationParameter,
    StorageThrottleImageParameter,
    StorageThrottleTypeParameter,
    WriteBPSParameter,
    WriteIOPSParameter,
)
from krkn_ai.models.cluster_components import Namespace, Pod, PVC
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class StorageThrottleScenario(Scenario):
    name: str = "storage-throttle"
    krknctl_name: str = "storage-throttle"
    krknhub_image: str = (
        "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:storage-throttle"
    )

    namespace: NamespaceParameter = NamespaceParameter()
    pvc_name: PVCNameParameter = PVCNameParameter()
    pod_name: PodNameParameter = PodNameParameter()
    mount_path: MountPathParameter = MountPathParameter()
    throttle_type: StorageThrottleTypeParameter = StorageThrottleTypeParameter()
    read_iops: ReadIOPSParameter = ReadIOPSParameter()
    write_iops: WriteIOPSParameter = WriteIOPSParameter()
    read_bps: ReadBPSParameter = ReadBPSParameter()
    write_bps: WriteBPSParameter = WriteBPSParameter()
    duration: StandardDurationParameter = StandardDurationParameter(value=60)
    image: StorageThrottleImageParameter = StorageThrottleImageParameter()

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        params = [self.namespace]
        if self.pvc_name.value:
            params.append(self.pvc_name)
        elif self.pod_name.value:
            params.append(self.pod_name)
        params.extend([self.mount_path, self.throttle_type])

        if self.throttle_type.value == "iops":
            params.extend([self.read_iops, self.write_iops])
        elif self.throttle_type.value == "bandwidth":
            params.extend([self.read_bps, self.write_bps])
        else:  # "both"
            params.extend(
                [self.read_iops, self.write_iops, self.read_bps, self.write_bps]
            )

        params.extend([self.duration, self.image])
        return params

    def mutate(self):
        if len(self._cluster_components.namespaces) == 0:
            raise ScenarioParameterInitError(
                "No namespaces found in cluster components"
            )

        namespace_pvc_tuple: List[Tuple[Namespace, PVC]] = []
        namespace_pod_tuple: List[Tuple[Namespace, Pod]] = []

        for namespace in self._cluster_components.namespaces:
            if namespace.pvcs:
                namespace_pvc_tuple.extend((namespace, pvc) for pvc in namespace.pvcs)
            if namespace.pods:
                namespace_pod_tuple.extend((namespace, pod) for pod in namespace.pods)

        if not namespace_pvc_tuple and not namespace_pod_tuple:
            raise ScenarioParameterInitError(
                "No PVCs or pods found in cluster components for storage-throttle scenario"
            )

        if namespace_pvc_tuple:
            namespace, pvc = rng.choice(namespace_pvc_tuple)
            self.namespace.value = namespace.name
            self.pvc_name.value = pvc.name
            self.pod_name.value = ""
        else:
            namespace, pod = rng.choice(namespace_pod_tuple)
            self.namespace.value = namespace.name
            self.pod_name.set_pod(namespace.name, pod)
            self.pvc_name.value = ""

        self.throttle_type.mutate()
        self.read_iops.mutate()
        self.write_iops.mutate()
        self.read_bps.mutate()
        self.write_bps.mutate()
