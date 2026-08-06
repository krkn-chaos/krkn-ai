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
        namespace, pvc = self._select_namespace_pvc("storage-throttle")
        self.namespace.value = namespace.name
        self.pvc_name.value = pvc.name
        self.pod_name.value = ""

        self.throttle_type.mutate()
        self.read_iops.mutate()
        self.write_iops.mutate()
        self.read_bps.mutate()
        self.write_bps.mutate()
