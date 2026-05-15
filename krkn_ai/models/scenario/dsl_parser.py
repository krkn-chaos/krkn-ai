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
        self.cluster_components = cluster_components.get_active_components()
        # Map of type names (as used in YAML) to Scenario classes
        self._type_map = {
            spec[0]
            .replace("_scenarios", "")
            .replace("_", "-"): spec[1]
            for spec in scenario_specs
        }
        # Add some aliases for convenience
        aliases = {
            "pod": "pod",
            "network": "network",
            "container": "container",
            "cpu-hog": "node-cpu-hog",
            "memory-hog": "node-memory-hog",
            "io-hog": "node-io-hog",
            "dns": "dns-outage",
            "pvc": "pvc",
            "kubevirt": "kubevirt",
        }
        for alias, target in aliases.items():
            if target in self._type_map:
                self._type_map[alias] = self._type_map[target]
            elif any(target in k for k in self._type_map):
                # Fallback for partial matches
                for k, v in self._type_map.items():
                    if target in k:
                        self._type_map[alias] = v
                        break

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
        step_by_name: Dict[str, Dict[str, Any]] = {}
        
        for step in steps:
            name = step.get("name")
            type_name = step.get("type")
            params = step.get("parameters", {})
            step_by_name[name] = step

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

        # 2. Build composition tree based on depends_on
        # We find the leaf nodes (scenarios that nothing depends on)
        # and work backwards. For simplicity, we assume a single linear chain or a tree.
        
        # Track what depends on what
        dependents: Dict[str, List[str]] = {name: [] for name in scenario_map}
        for name, step in step_by_name.items():
            parent = step.get("depends_on")
            if parent:
                if parent not in scenario_map:
                    raise ValueError(f"Step '{name}' depends on unknown step '{parent}'")
                dependents[parent].append(name)

        # Roots are nodes with no dependencies
        roots = [name for name, step in step_by_name.items() if not step.get("depends_on")]
        if not roots:
            raise ValueError("Circular dependency detected (no root steps found)")

        # Recursive builder to handle nested composition
        def build_composed(node_name: str) -> BaseScenario:
            current = scenario_map[node_name]
            children_names = dependents[node_name]
            
            if not children_names:
                return current
            
            # Recursively build all child subtrees
            child_scenarios = [build_composed(name) for name in children_names]
            
            # 1. Combine all children into a parallel "sibling block" (NONE dependency)
            sibling_block = child_scenarios[0]
            for i in range(1, len(child_scenarios)):
                sibling_block = CompositeScenario(
                    name=f"Siblings: {children_names[i-1]} || {children_names[i]}",
                    scenario_a=child_scenarios[i],
                    scenario_b=sibling_block,
                    dependency=CompositeDependency.NONE
                )
            
            # 2. Make the entire sibling block depend on the current node (A_ON_B)
            return CompositeScenario(
                name=f"Composition: {node_name} -> [{', '.join(children_names)}]",
                scenario_a=sibling_block,
                scenario_b=current,
                dependency=CompositeDependency.A_ON_B
            )

        # We return the first root (supporting multiple roots would require a top-level container)
        return build_composed(roots[0])
