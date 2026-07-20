"""Tests for templates/generator.py scenario rendering."""

import yaml

from krkn_ai.templates.generator import create_krkn_ai_template
from krkn_ai.models.scenario.factory import scenario_specs
from krkn_ai.models.config import HealthCheckConfig

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


def _health_checks(rendered: str):
    """Return the health_checks mapping from rendered YAML (None if commented)."""
    return yaml.safe_load(rendered).get("health_checks")


class TestHealthCheckRendering:
    def test_none_keeps_commented_example(self):
        """health_checks=None leaves the block commented out."""
        rendered = create_krkn_ai_template(KUBECONFIG, DATA)
        assert _health_checks(rendered) is None
        assert "# health_checks:" in rendered

    def test_empty_list_falls_back_identically(self):
        """An empty recommendation renders the same as None."""
        assert create_krkn_ai_template(
            KUBECONFIG, DATA, None, []
        ) == create_krkn_ai_template(KUBECONFIG, DATA)

    def test_enabled_apps_render_live_block(self):
        """Endpoints with probe+active render an active health_checks block."""
        apps = [
            {
                "name": "cart",
                "url": "http://1.2.3.4:80/health",
                "probe": True,
                "active": True,
            },
            {
                "name": "user",
                "url": "https://1.2.3.4:443/user/ready",
                "probe": True,
                "active": True,
            },
        ]
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, None, apps)
        block = _health_checks(rendered)
        assert len(block["applications"]) == 2
        HealthCheckConfig(**block)

    def test_boolean_like_name_stays_a_string(self):
        """A name like 'on' stays a string, not a bool."""
        rendered = create_krkn_ai_template(
            KUBECONFIG,
            DATA,
            None,
            [{"name": "on", "url": "http://x/y", "probe": True, "active": True}],
        )
        block = _health_checks(rendered)
        assert block["applications"][0]["name"] == "on"
        HealthCheckConfig(**block)

    def test_no_probe_comments_with_reason(self):
        """An entry with probe=False renders commented with '(no probe)'."""
        apps = [
            {
                "name": "web",
                "url": "http://1.2.3.4:8080/",
                "probe": False,
                "active": True,
            },
        ]
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, None, apps)
        assert "# health_checks:" in rendered
        assert "(no probe)" in rendered
        assert _health_checks(rendered) is None

    def test_unreachable_comments_with_reason(self):
        """An entry with active=False renders commented with '(unreachable)'."""
        apps = [
            {
                "name": "cart",
                "url": "http://1.2.3.4:80/health",
                "probe": True,
                "active": False,
            },
        ]
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, None, apps)
        assert "# health_checks:" in rendered
        assert "(unreachable)" in rendered
        assert _health_checks(rendered) is None

    def test_no_probe_unreachable_comments_with_both_reasons(self):
        """An entry with both False renders '(no probe, unreachable)'."""
        apps = [
            {
                "name": "web",
                "url": "http://1.2.3.4:8080/",
                "probe": False,
                "active": False,
            },
        ]
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, None, apps)
        assert "(no probe, unreachable)" in rendered
        assert _health_checks(rendered) is None

    def test_mixed_enabled_and_disabled(self):
        """Enabled entries render as YAML, disabled as comments with reason."""
        apps = [
            {
                "name": "cart",
                "url": "http://1.2.3.4:80/health",
                "probe": True,
                "active": True,
            },
            {
                "name": "web",
                "url": "http://1.2.3.4:8080/",
                "probe": False,
                "active": True,
            },
        ]
        rendered = create_krkn_ai_template(KUBECONFIG, DATA, None, apps)
        block = _health_checks(rendered)
        assert len(block["applications"]) == 1
        assert block["applications"][0]["name"] == "cart"
        assert '# - name: "web"' in rendered
        assert "(no probe)" in rendered
        HealthCheckConfig(**block)
