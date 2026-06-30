"""Tests for templates/generator.py scenario rendering."""

import yaml

from krkn_ai.templates.generator import create_krkn_ai_template
from krkn_ai.models.scenario.factory import scenario_specs

KUBECONFIG = "/tmp/kubeconfig"
DATA: dict = {"namespaces": []}
ALL_NAMES = [name for name, _ in scenario_specs]


def _scenario_block(rendered: str) -> dict:
    """Return the {scenario: enable} mapping from rendered YAML."""
    doc = yaml.safe_load(rendered)
    return {k: v["enable"] for k, v in doc["scenario"].items()}


class TestScenarioRendering:
    def test_none_falls_back_to_all_disabled(self):
        """scenario_enables=None renders all scenarios disabled."""
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, None)
        enables = _scenario_block(rendered)
        assert not any(enables.values())

    def test_no_arg_matches_none(self):
        """Omitting scenario_enables matches None."""
        assert create_krkn_ai_template(KUBECONFIG, DATA) == create_krkn_ai_template(
            KUBECONFIG, DATA, None
        )

    def test_dict_enables_only_true_scenarios(self):
        """A dict enables exactly the True scenarios."""
        enables_dict = {n: n in {"pvc_scenarios", "node_cpu_hog"} for n in ALL_NAMES}
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, enables_dict)
        enables = _scenario_block(rendered)
        assert enables["pvc-scenarios"] is True
        assert enables["node-cpu-hog"] is True
        assert enables["pod-scenarios"] is False
        assert sum(enables.values()) == 2

    def test_all_false_disables_all(self):
        """All-false dict disables every scenario."""
        enables_dict = {n: False for n in ALL_NAMES}
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, enables_dict)
        enables = _scenario_block(rendered)
        assert not any(enables.values())

    def test_rendered_output_is_valid_yaml_and_lowercase(self):
        """Booleans render lowercase and output is valid YAML."""
        enables_dict = {n: n == "pod_scenarios" for n in ALL_NAMES}
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, enables_dict)
        assert "enable: true" in rendered
        assert "enable: True" not in rendered
        yaml.safe_load(rendered)  # does not raise
