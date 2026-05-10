import yaml
from typing import List, Dict, Any, Optional
from krkn_ai.models.scenario.base import (
    BaseScenario,
    Scenario,
    CompositeScenario,
    CompositeDependency,
)
from krkn_ai.models.scenario.factory import scenario_specs
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class ScenarioDSLParser:
    """
    Parses YAML-based Chaos Recipes into executable Scenario objects.
    Enables expert-guided seed populations for the Genetic Algorithm.
    """

    def __init__(self, cluster_components: ClusterComponents):
        self.cluster_components = cluster_components
        # Map of type names (as used in YAML) to Scenario classes
        self._type_map = {
            spec[0]
            .replace("_scenarios", "")
            .replace("_scenarios", "")
            .replace("_", "-"): spec[1]
            for spec in scenario_specs
        }
        # Add some aliases for convenience
        self._type_map.update(
            {
                "pod": self._type_map.get("pod"),
                "network": self._type_map.get("network"),
                "container": self._type_map.get("container"),
                "cpu-hog": self._type_map.get("node-cpu-hog"),
                "memory-hog": self._type_map.get("node-memory-hog"),
                "io-hog": self._type_map.get("node-io-hog"),
            }
        )

    def parse_file(self, file_path: str) -> List[BaseScenario]:
        with open(file_path, "r") as f:
            data = yaml.safe_load(f)
        return self.parse_dict(data)

    def parse_dict(self, data: Dict[str, Any]) -> List[BaseScenario]:
        recipes = data.get("recipes", [])
        if not recipes:
            # Check if the root is a single recipe
            if "name" in data and "steps" in data:
                recipes = [data]
            else:
                logger.warning("No recipes found in DSL data")
                return []

        parsed_scenarios = []
        for recipe in recipes:
            try:
                scenario = self._build_recipe(recipe)
                if scenario:
                    parsed_scenarios.append(scenario)
            except Exception as e:
                logger.error(
                    f"Failed to parse recipe '{recipe.get('name', 'unknown')}': {e}"
                )

        return parsed_scenarios

    def _build_recipe(self, recipe: Dict[str, Any]) -> Optional[BaseScenario]:
        steps = recipe.get("steps", [])
        if not steps:
            return None

        # 1. Create all base scenarios
        scenario_map: Dict[str, Scenario] = {}
        for step in steps:
            name = step.get("name")
            type_name = step.get("type")
            params = step.get("parameters", {})

            cls = self._type_map.get(type_name)
            if not cls:
                raise ValueError(f"Unknown scenario type: {type_name}")

            # Instantiate scenario
            instance = cls(cluster_components=self.cluster_components)

            # Override parameters if provided
            if params:
                for p in instance.parameters:
                    p_name = p.get_name(False)
                    if p_name in params:
                        p.value = params[p_name]

            scenario_map[name] = instance

        # 2. Build composition tree
        # For simplicity, we support a linear chain or a single dependency
        # A more complex graph would require a different approach.
        # We'll follow the "depends_on" field.

        root_scenarios = []
        for step in steps:
            if not step.get("depends_on"):
                root_scenarios.append(step.get("name"))

        if not root_scenarios:
            raise ValueError("Circular dependency or missing root step in recipe")

        # We'll return the first root, potentially composed with others
        # In this first version, we'll just handle linear chains
        # Recipe DSL V1: Linear chain
        current_scenario = scenario_map[steps[0]["name"]]
        for i in range(1, len(steps)):
            next_step = steps[i]
            next_scenario = scenario_map[next_step["name"]]

            # Create composite: Next depends on Current
            current_scenario = CompositeScenario(
                name=f"{recipe.get('name')} - Step {i + 1}",
                scenario_a=next_scenario,
                scenario_b=current_scenario,
                dependency=CompositeDependency.A_ON_B,
            )

        return current_scenario
