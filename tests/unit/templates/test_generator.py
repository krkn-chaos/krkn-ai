"""Tests for templates/generator.py scenario rendering."""

import yaml

from krkn_ai.templates.generator import (
    create_krkn_ai_template,
    STATIC_SCENARIO_ENABLES,
)

KUBECONFIG = "/tmp/kubeconfig"
DATA: dict = {"namespaces": []}


def _scenario_block(rendered: str) -> dict:
    """Return the {scenario: enable} mapping from rendered YAML."""
    doc = yaml.safe_load(rendered)
    return {k: v["enable"] for k, v in doc["scenario"].items()}


class TestScenarioRendering:
    def test_none_falls_back_to_static_defaults(self):
        """dynamic=None renders the static defaults."""
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, None)
        enables = _scenario_block(rendered)
        expected = {k: (v == "true") for k, v in STATIC_SCENARIO_ENABLES.items()}
        assert enables == expected
        # spot-check a couple of defaults
        assert enables["pod-scenarios"] is True
        assert enables["dns-outage"] is True
        assert enables["pvc-scenarios"] is False

    def test_no_dynamic_arg_matches_none(self):
        """Omitting dynamic matches dynamic=None."""
        assert create_krkn_ai_template(KUBECONFIG, DATA) == create_krkn_ai_template(
            KUBECONFIG, DATA, None
        )

    def test_set_enables_only_listed_scenarios(self):
        """A set enables exactly the listed scenarios."""
        rendered = create_krkn_ai_template(
            KUBECONFIG, DATA, {"scenarios": {"pvc-scenarios", "node-cpu-hog"}}
        )
        enables = _scenario_block(rendered)
        assert enables["pvc-scenarios"] is True
        assert enables["node-cpu-hog"] is True
        assert enables["pod-scenarios"] is False
        assert sum(enables.values()) == 2

    def test_empty_set_disables_all(self):
        """An empty set disables every scenario."""
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, {"scenarios": set()})
        enables = _scenario_block(rendered)
        assert not any(enables.values())

    def test_rendered_output_is_valid_yaml_and_lowercase(self):
        """Booleans render lowercase and output is valid YAML."""
        rendered = create_krkn_ai_template(
            KUBECONFIG, DATA, {"scenarios": {"pod-scenarios"}}
        )
        assert "enable: true" in rendered
        assert "enable: True" not in rendered
        yaml.safe_load(rendered)  # does not raise
