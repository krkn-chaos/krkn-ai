import contextlib
import logging
from typing import Dict, List, Tuple
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.config import ConfigFile, FitnessFunction, ScenarioConfig
from krkn_ai.models.custom_errors import (
    MissingScenarioError,
    ScenarioInitError,
    ScenarioParameterInitError,
)
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.scenario_network import NetworkScenario
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.rng import rng
from krkn_ai.cluster import initialize_kubeconfig

from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.scenario_pod import PodScenario
from krkn_ai.models.scenario.scenario_app_outage import AppOutageScenario
from krkn_ai.models.scenario.scenario_container import ContainerScenario
from krkn_ai.models.scenario.scenario_cpu_hog import NodeCPUHogScenario
from krkn_ai.models.scenario.scenario_memory_hog import NodeMemoryHogScenario
from krkn_ai.models.scenario.scenario_time import TimeScenario
from krkn_ai.models.scenario.scenario_dns_outage import DnsOutageScenario
from krkn_ai.models.scenario.scenario_syn_flood import SynFloodScenario
from krkn_ai.models.scenario.scenario_io_hog import NodeIOHogScenario
from krkn_ai.models.scenario.scenario_pvc import PVCScenario
from krkn_ai.models.scenario.scenario_kubevirt import KubevirtDisruptionScenario
from krkn_ai.models.scenario.scenario_storage_throttle import StorageThrottleScenario
from krkn_ai.models.scenario.scenario_service_disruption import (
    ServiceDisruptionScenario,
)

logger = get_logger(__name__)


@contextlib.contextmanager
def _suppressed_factory_warnings():
    # suppress warnings for discover
    previous = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous)


scenario_specs = [
    ("pod_scenarios", PodScenario),
    ("application_outages", AppOutageScenario),
    ("container_scenarios", ContainerScenario),
    ("node_cpu_hog", NodeCPUHogScenario),
    ("node_memory_hog", NodeMemoryHogScenario),
    ("node_io_hog", NodeIOHogScenario),
    ("time_scenarios", TimeScenario),
    ("network_scenarios", NetworkScenario),
    ("dns_outage", DnsOutageScenario),
    ("syn_flood", SynFloodScenario),
    ("pvc_scenarios", PVCScenario),
    ("kubevirt_scenarios", KubevirtDisruptionScenario),
    ("storage_throttle", StorageThrottleScenario),
    ("service_disruption", ServiceDisruptionScenario),
]

# Scenarios with a cluster-critical blast radius. They are fully supported, but
# are only ever run when the config explicitly sets ``allow_dangerous_scenarios:
# true`` -- their own ``enable`` flag is not sufficient on its own.
#
# Service disruption deletes entire namespaces, destroying every resource inside
# them; unlike a pod or container kill, recovery depends on an operator or
# GitOps controller reconciling the namespace back.
DANGEROUS_SCENARIOS = {"service_disruption"}


class ScenarioFactory:
    @staticmethod
    def _blocked_dangerous_scenarios(config: ConfigFile) -> List[str]:
        """User-facing keys of enabled dangerous scenarios blocked by the gate."""
        if config.allow_dangerous_scenarios:
            return []
        blocked = []
        for attr, _ in scenario_specs:
            scenario_cfg = getattr(config.scenario, attr)
            if (
                attr in DANGEROUS_SCENARIOS
                and scenario_cfg is not None
                and scenario_cfg.enable
            ):
                blocked.append(attr.replace("_", "-"))
        return blocked

    @staticmethod
    def list_scenarios(config: ConfigFile) -> List[Tuple[str, type[Scenario]]]:
        # List all enabled scenarios from config, gating dangerous ones behind
        # the explicit allow_dangerous_scenarios opt-in.
        candidates = []
        for attr, factory in scenario_specs:
            scenario_cfg = getattr(config.scenario, attr)
            if scenario_cfg is None or not scenario_cfg.enable:
                continue
            if attr in DANGEROUS_SCENARIOS and not config.allow_dangerous_scenarios:
                logger.warning(
                    "Scenario '%s' is enabled but has a cluster-critical blast "
                    "radius; skipping it because 'allow_dangerous_scenarios' is "
                    "not set. Set allow_dangerous_scenarios: true to run it.",
                    attr.replace("_", "-"),
                )
                continue
            candidates.append((attr, factory))
        return candidates

    @staticmethod
    def generate_valid_scenarios(
        config: ConfigFile,
    ) -> List[Tuple[str, type[Scenario]]]:
        """
        Validate all scenarios that are set in config and are valid.

        Returns a list of valid scenarios.
        """
        # Get all scenarios that are set in config
        candidates = ScenarioFactory.list_scenarios(config)

        if len(candidates) == 0:
            blocked = ScenarioFactory._blocked_dangerous_scenarios(config)
            if blocked:
                raise MissingScenarioError(
                    "The only enabled scenario(s) ({}) are cluster-critical and "
                    "were blocked. Set 'allow_dangerous_scenarios: true' in your "
                    "config to run them.".format(", ".join(blocked))
                )
            raise MissingScenarioError(
                "No scenarios found. Please provide atleast 1 scenario."
            )

        # Initialize kubeconfig for PVC utilities
        initialize_kubeconfig(config.kubeconfig_file_path)

        # Get active components (filtered out disabled ones)
        active_components = config.cluster_components.get_active_components()

        # Validate scenarios and find valid scenarios
        valid_scenarios = []
        for name, cls in candidates:
            try:
                # Try to instantiate the scenario with active components only
                cls(cluster_components=active_components)
                valid_scenarios.append((name, cls))
            except ScenarioParameterInitError as error:
                logger.warning(
                    "Unable to initialize scenario %s, please make sure cluster components for scenario are valid",
                    name,
                )
                logger.debug("Error details: %s", error)
            except Exception as error:
                logger.warning("Unable to instantiate scenario %s: %s", name, error)

        if len(valid_scenarios) == 0:
            raise MissingScenarioError(
                "No valid scenarios found. Please validate cluster components in config file."
            )

        logger.debug(
            "Identified %d valid scenarios: %s",
            len(valid_scenarios),
            [name for name, _ in valid_scenarios],
        )
        return valid_scenarios

    @staticmethod
    def generate_random_scenario(
        config: ConfigFile,
        candidates: List[Tuple[str, type[Scenario]]],
    ):
        """
        Generate a random scenario from the list of valid scenarios.
        """
        try:
            # Get active components (filtered out disabled ones)
            active_components = config.cluster_components.get_active_components()
            # Unpack Scenario class and create instance
            _, cls = rng.choice(candidates)
            return cls(cluster_components=active_components)
        except Exception as error:
            raise ScenarioInitError("Unable to initialize scenario: %s", error)

    @staticmethod
    def create_dummy_scenario():
        return DummyScenario(cluster_components=ClusterComponents())

    @staticmethod
    def recommend_enabled_scenarios(
        cluster_components: ClusterComponents, kubeconfig: str
    ) -> Dict[str, bool]:
        names = [name for name, _ in scenario_specs]
        all_disabled = {n: False for n in names}
        try:
            config = ConfigFile(
                kubeconfig_file_path=kubeconfig,
                fitness_function=FitnessFunction(query="placeholder"),
                scenario=ScenarioConfig(**{n: {"enable": True} for n in names}),
                cluster_components=cluster_components,
            )
            with _suppressed_factory_warnings():
                valid = ScenarioFactory.generate_valid_scenarios(config)
        except MissingScenarioError:
            logger.warning(
                "No valid scenarios found for this cluster. "
                "All scenarios disabled. "
                "Check your cluster components or re-run discover."
            )
            return all_disabled
        except Exception as error:
            logger.debug("Scenario recommendation failed: %s", error)
            return all_disabled
        valid_names = {name for name, _ in valid}
        return {n: n in valid_names for n in names}
