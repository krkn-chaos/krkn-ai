from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    DeleteCountParameter,
    LabelSelectorParameter,
    NamespaceParameter,
    RunsParameter,
)


class ServiceDisruptionScenario(Scenario):
    """Service disruption (namespace deletion) scenario.

    Deletes a target namespace and waits for it to be recreated, exercising an
    application's ability to recover from losing its namespace-scoped resources.
    Gated behind ``allow_dangerous_scenarios`` since namespace deletion is not
    self-recovering.
    See https://krkn-chaos.dev/docs/scenarios/service-disruption-scenarios/
    """

    name: str = "service-disruption"
    krknctl_name: str = "service-disruption-scenarios"
    krknhub_image: str = (
        "containers.krkn-chaos.dev/krkn-chaos/krkn-hub:service-disruption-scenarios"
    )

    namespace: NamespaceParameter = NamespaceParameter()
    label_selector: LabelSelectorParameter = LabelSelectorParameter()
    delete_count: DeleteCountParameter = DeleteCountParameter()
    runs: RunsParameter = RunsParameter()

    def __init__(self, **data):
        super().__init__(**data)
        self.mutate()

    @property
    def parameters(self):
        # NAMESPACE and LABEL_SELECTOR are mutually exclusive in krkn;
        # only emit label_selector when it is actually set.
        params = [self.namespace]
        if self.label_selector.value:
            params.append(self.label_selector)
        params.extend([self.delete_count, self.runs])
        return params

    def mutate(self):
        candidates = [ns for ns in self._cluster_components.namespaces if ns.services]
        if not candidates:
            raise ScenarioParameterInitError(
                "No namespaces with services found for service disruption scenario"
            )

        namespace = rng.choice(candidates)
        # Target a specific namespace by name; delete_count stays at 1.
        # runs varies to give the genetic algorithm room to explore.
        self.namespace.value = namespace.name
        self.label_selector.value = ""
        self.delete_count.value = 1
        self.runs.value = rng.randint(1, 3)
