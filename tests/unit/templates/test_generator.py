"""
Tests for krkn_ai.templates.generator
"""

import yaml

from krkn_ai.templates.generator import _compute_scenario_flags, create_krkn_ai_template


class TestComputeScenarioFlags:
    """Tests for _compute_scenario_flags helper."""

    def test_flags_all_true_when_resources_present(self):
        """All flags should be True when every resource type is discovered."""
        data = {
            "namespaces": [
                {
                    "name": "default",
                    "pods": [{"name": "pod-1"}],
                    "services": [{"name": "svc-1"}],
                    "pvcs": [{"name": "pvc-1"}],
                    "vmis": [{"name": "vmi-1"}],
                }
            ],
            "nodes": [
                {
                    "name": "node-1",
                    "interfaces": ["eth0"],
                }
            ],
        }
        flags = _compute_scenario_flags(data)
        assert flags["has_pods"] is True
        assert flags["has_services"] is True
        assert flags["has_pvcs"] is True
        assert flags["has_vmis"] is True
        assert flags["has_interfaces"] is True

    def test_flags_all_false_when_no_resources(self):
        """All flags should be False for an empty cluster."""
        data = {"namespaces": [], "nodes": []}
        flags = _compute_scenario_flags(data)
        assert flags["has_pods"] is False
        assert flags["has_services"] is False
        assert flags["has_pvcs"] is False
        assert flags["has_vmis"] is False
        assert flags["has_interfaces"] is False

    def test_flags_false_when_keys_missing(self):
        """Flags should be False when exclude_defaults omits empty lists."""
        # model_dump(exclude_defaults=True) drops keys with default values
        data = {
            "namespaces": [{"name": "default"}],
            "nodes": [{"name": "node-1"}],
        }
        flags = _compute_scenario_flags(data)
        assert flags["has_pods"] is False
        assert flags["has_services"] is False
        assert flags["has_pvcs"] is False
        assert flags["has_vmis"] is False
        assert flags["has_interfaces"] is False

    def test_flags_empty_dict(self):
        """Flags should be False for a completely empty dict."""
        flags = _compute_scenario_flags({})
        assert flags["has_pods"] is False
        assert flags["has_services"] is False
        assert flags["has_pvcs"] is False
        assert flags["has_vmis"] is False
        assert flags["has_interfaces"] is False

    def test_pvcs_true_vmis_false_selective(self):
        """Only the PVC flag should be True when only PVCs are present."""
        data = {
            "namespaces": [
                {
                    "name": "storage-ns",
                    "pvcs": [{"name": "data-pvc"}],
                }
            ],
            "nodes": [{"name": "node-1"}],
        }
        flags = _compute_scenario_flags(data)
        assert flags["has_pods"] is False
        assert flags["has_pvcs"] is True
        assert flags["has_vmis"] is False
        assert flags["has_interfaces"] is False

    def test_multiple_namespaces_aggregated(self):
        """Flags should be True if any namespace has the resource."""
        data = {
            "namespaces": [
                {"name": "ns-a"},
                {"name": "ns-b", "pods": [{"name": "pod-b"}]},
            ],
            "nodes": [],
        }
        flags = _compute_scenario_flags(data)
        assert flags["has_pods"] is True
        assert flags["has_services"] is False


class TestCreateKrknAiTemplate:
    """Tests for the template rendering with scenario flags."""

    def _render(self, cluster_data: dict) -> dict:
        """Helper: render the template and parse the YAML output."""
        output = create_krkn_ai_template("/path/to/kubeconfig", cluster_data)
        return yaml.safe_load(output)

    def test_pvc_scenario_enabled_when_pvcs_discovered(self):
        """pvc-scenarios should be enabled when PVCs exist."""
        data = {
            "namespaces": [
                {
                    "name": "default",
                    "pods": [{"name": "pod-1"}],
                    "pvcs": [{"name": "pvc-1"}],
                }
            ],
            "nodes": [],
        }
        config = self._render(data)
        assert config["scenario"]["pvc-scenarios"]["enable"] is True

    def test_pvc_scenario_disabled_when_no_pvcs(self):
        """pvc-scenarios should be disabled when no PVCs exist."""
        data = {
            "namespaces": [
                {
                    "name": "default",
                    "pods": [{"name": "pod-1"}],
                }
            ],
            "nodes": [],
        }
        config = self._render(data)
        assert config["scenario"]["pvc-scenarios"]["enable"] is False

    def test_kubevirt_scenario_enabled_when_vmis_discovered(self):
        """kubevirt-scenarios should be enabled when VMIs exist."""
        data = {
            "namespaces": [
                {
                    "name": "virt-ns",
                    "vmis": [{"name": "vmi-1"}],
                }
            ],
            "nodes": [],
        }
        config = self._render(data)
        assert config["scenario"]["kubevirt-scenarios"]["enable"] is True

    def test_kubevirt_scenario_disabled_when_no_vmis(self):
        """kubevirt-scenarios should be disabled when no VMIs exist."""
        data = {"namespaces": [{"name": "default"}], "nodes": []}
        config = self._render(data)
        assert config["scenario"]["kubevirt-scenarios"]["enable"] is False

    def test_pod_scenarios_follow_pod_availability(self):
        """pod-scenarios and container-scenarios should follow pod presence."""
        data = {
            "namespaces": [
                {"name": "default", "pods": [{"name": "p1"}]},
            ],
            "nodes": [],
        }
        config = self._render(data)
        assert config["scenario"]["pod-scenarios"]["enable"] is True
        assert config["scenario"]["container-scenarios"]["enable"] is True

    def test_network_scenarios_follow_interface_availability(self):
        """network-scenarios and syn-flood follow node interface presence."""
        data = {
            "namespaces": [{"name": "default"}],
            "nodes": [{"name": "node-1", "interfaces": ["eth0"]}],
        }
        config = self._render(data)
        assert config["scenario"]["network-scenarios"]["enable"] is True
        assert config["scenario"]["syn-flood"]["enable"] is True

    def test_node_hog_scenarios_always_disabled(self):
        """node-*-hog and time-scenarios must always be disabled (safe defaults)."""
        data = {
            "namespaces": [
                {
                    "name": "default",
                    "pods": [{"name": "p1"}],
                    "services": [{"name": "s1"}],
                    "pvcs": [{"name": "pvc-1"}],
                    "vmis": [{"name": "vmi-1"}],
                }
            ],
            "nodes": [{"name": "node-1", "interfaces": ["eth0"]}],
        }
        config = self._render(data)
        assert config["scenario"]["node-cpu-hog"]["enable"] is False
        assert config["scenario"]["node-memory-hog"]["enable"] is False
        assert config["scenario"]["node-io-hog"]["enable"] is False
        assert config["scenario"]["time-scenarios"]["enable"] is False

    def test_empty_cluster_disables_all_conditional_scenarios(self):
        """An empty cluster should disable all dynamic scenarios."""
        data = {"namespaces": [], "nodes": []}
        config = self._render(data)
        assert config["scenario"]["pod-scenarios"]["enable"] is False
        assert config["scenario"]["application-outages"]["enable"] is False
        assert config["scenario"]["container-scenarios"]["enable"] is False
        assert config["scenario"]["network-scenarios"]["enable"] is False
        assert config["scenario"]["dns-outage"]["enable"] is False
        assert config["scenario"]["syn-flood"]["enable"] is False
        assert config["scenario"]["pvc-scenarios"]["enable"] is False
        assert config["scenario"]["kubevirt-scenarios"]["enable"] is False

    def test_kubeconfig_path_rendered(self):
        """The kubeconfig path should appear in the rendered output."""
        data = {"namespaces": [], "nodes": []}
        config = self._render(data)
        assert config["kubeconfig_file_path"] == "/path/to/kubeconfig"
