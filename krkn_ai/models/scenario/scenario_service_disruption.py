from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.rng import rng
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import (
    DeleteCountParameter,
    LabelSelectorParameter,
    NamespaceParameter,
    RunsParameter,
)

# Cluster-critical namespaces that must never be a deletion target, even when a
# user has opted in. discover's default `--namespace .*` pulls these into
# cluster_components, so guard against selecting them here.
_SYSTEM_NAMESPACES = frozenset({"default"})
_SYSTEM_NAMESPACE_PREFIXES = ("kube-", "openshift")


def _is_system_namespace(name: str) -> bool:
    return name in _SYSTEM_NAMESPACES or name.startswith(_SYSTEM_NAMESPACE_PREFIXES)


class ServiceDisruptionScenario(Scenario):
    """Service disruption (namespace deletion) scenario.

    Deletes a target namespace and waits for it to be recreated, exercising an
    application's ability to recover from losing its namespace-scoped resources.
    See https://krkn-chaos.dev/docs/scenarios/service-disruption-scenarios/.
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
        # NAMESPACE and LABEL_SELECTOR are mutually exclusive in krkn, so only
        # emit label_selector when it is actually set -- never pass an empty
        # --label-selector "" alongside NAMESPACE.
        params = [self.namespace]
        if self.label_selector.value:
            params.append(self.label_selector)
        params.extend([self.delete_count, self.runs])
        return params

    def mutate(self):
        # Only target non-system namespaces that actually run services: deleting
        # a namespace with no services has no meaningful blast radius, and
        # cluster-critical namespaces (kube-*, openshift*, default) must never be
        # a target even after the user opts into dangerous scenarios.
        candidates = [
            ns
            for ns in self._cluster_components.namespaces
            if ns.services and not _is_system_namespace(ns.name)
        ]
        if not candidates:
            raise ScenarioParameterInitError(
                "No non-system namespaces with services found for service "
                "disruption scenario"
            )

        namespace = rng.choice(candidates)

        # Target a specific namespace by name; label_selector stays empty. With a
        # single named namespace exactly one namespace matches, so delete_count
        # stays at 1; runs varies to give the genetic algorithm room to explore
        # repeated disruptions.
        self.namespace.value = namespace.name
        self.label_selector.value = ""
        self.delete_count.value = 1
        self.runs.value = rng.randint(1, 3)
