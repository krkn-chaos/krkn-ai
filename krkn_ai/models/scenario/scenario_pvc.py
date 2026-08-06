from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    FillPercentageParameter,
    NamespaceParameter,
    PodNameParameter,
    PVCNameParameter,
    StandardDurationParameter,
)
from krkn_ai.cluster import get_pvc_usage_percentage
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class PVCScenario(Scenario):
    name: str = "pvc-scenarios"
    krknctl_name: str = "pvc-scenarios"
    krknhub_image: str = "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:pvc-scenarios"

    namespace: NamespaceParameter = NamespaceParameter()
    pvc_name: PVCNameParameter = PVCNameParameter()
    pod_name: PodNameParameter = PodNameParameter()
    fill_percentage: FillPercentageParameter = FillPercentageParameter()
    duration: StandardDurationParameter = StandardDurationParameter(value=60)

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        # pvc-name and pod-name are mutually exclusive, at least one is required
        params = [
            self.namespace,
            self.fill_percentage,
            self.duration,
        ]
        if self.pvc_name.value:
            params.insert(1, self.pvc_name)
        elif self.pod_name.value:
            params.insert(1, self.pod_name)
        return params

    def mutate(self):
        namespace, pvc = self._select_namespace_pvc("PVC")
        self.namespace.value = namespace.name
        self.pvc_name.value = pvc.name
        self.pod_name.value = ""  # Leave empty when using pvc-name

        min_usage = None
        try:
            current_usage = get_pvc_usage_percentage(
                pvc_name=pvc.name, namespace=namespace.name
            )
            if current_usage is not None:
                min_usage = current_usage
        except Exception as e:
            logger.debug(
                "Failed to get real-time PVC usage for %s: %s",
                pvc.name,
                str(e),
            )

        self.fill_percentage.mutate(min_value=min_usage)
