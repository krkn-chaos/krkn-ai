"""Tests for utils/fs.py"""

from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from krkn_ai.utils.fs import (
    read_config_from_file,
    save_discovery,
    merge_components,
)
from krkn_ai.templates.generator import create_krkn_ai_template
from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Namespace,
    Pod,
    Node,
)


class TestParamParsing:
    def test_param_with_base64_value_does_not_crash(self):
        """base64 secrets with = should not crash"""
        p = "SECRET=aGVsbG8="
        key, value = p.split("=", 1)
        assert key == "SECRET"
        assert value == "aGVsbG8="

    def test_param_with_password_containing_equals(self):
        """passwords with = should not crash"""
        p = "DB_PASSWORD=pass=word123"
        key, value = p.split("=", 1)
        assert key == "DB_PASSWORD"
        assert value == "pass=word123"

    def test_normal_param_still_works(self):
        """normal params without = still work"""
        p = "KEY=value"
        key, value = p.split("=", 1)
        assert key == "KEY"
        assert value == "value"

    def test_param_without_equals_sign(self):
        """param without = should assign empty string as value"""
        p = "JUST_A_KEY"
        if "=" in p:
            key, value = p.split("=", 1)
        else:
            key, value = p, ""
        assert key == "JUST_A_KEY"
        assert value == ""


class TestReadConfigFromFileHeaders:
    def _write_config(self, path):
        config = {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "health_checks": {
                "headers": {"Authorization": "Bearer $GLOBAL_TOKEN"},
                "applications": [
                    {
                        "name": "api",
                        "url": "http://localhost/health",
                        "headers": {"X-Tenant": "$TENANT_ID"},
                    }
                ],
            },
        }
        with open(path, "w") as f:
            yaml.dump(config, f)

    def test_headers_stay_as_templates_at_load_time(self, tmp_path):
        """Header values are not substituted at load — resolution happens at request time"""
        config_file = str(tmp_path / "config.yaml")
        self._write_config(config_file)
        config = read_config_from_file(
            config_file, param=["GLOBAL_TOKEN=mytoken", "TENANT_ID=acme"]
        )
        assert config.health_checks.headers["Authorization"] == "Bearer $GLOBAL_TOKEN"

    def test_endpoint_headers_stay_as_templates_at_load_time(self, tmp_path):
        """Per-endpoint header values are not substituted at load"""
        config_file = str(tmp_path / "config.yaml")
        self._write_config(config_file)
        config = read_config_from_file(
            config_file, param=["GLOBAL_TOKEN=mytoken", "TENANT_ID=acme"]
        )
        assert config.health_checks.applications[0].headers["X-Tenant"] == "$TENANT_ID"

    def test_url_param_substitution_applied_at_load_time(self, tmp_path):
        """URL $PARAM substitution happens at load time via -p flag"""
        config = {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "health_checks": {
                "applications": [{"name": "api", "url": "http://$HOST/health"}]
            },
        }
        config_file = str(tmp_path / "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)
        result = read_config_from_file(config_file, param=["HOST=myhost.com"])
        assert result.health_checks.applications[0].url == "http://myhost.com/health"

    def test_no_crash_when_headers_absent(self, tmp_path):
        """Test config without headers loads fine — guards on absent keys don't raise"""
        config = {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "health_checks": {
                "applications": [{"name": "api", "url": "http://localhost/health"}]
            },
        }
        config_file = str(tmp_path / "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)
        result = read_config_from_file(config_file, param=["KEY=value"])
        assert result.health_checks.headers is None
        assert result.health_checks.applications[0].headers is None

    def test_partial_elastic_config_uses_defaults_with_params(self, tmp_path):
        """Partial elastic config should not fail before Pydantic applies defaults."""
        config = {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "elastic": {"server": "https://$ES_HOST"},
        }
        config_file = str(tmp_path / "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        result = read_config_from_file(config_file, param=["ES_HOST=example.com"])

        assert result.elastic.server == "https://example.com"
        assert result.elastic.enable is False
        assert result.elastic.port == 9200
        assert result.elastic.verify_certs is True

    def test_read_config_merges_cli_params_with_defaults(self, tmp_path):
        """CLI parameter overrides should merge with default config file parameters, not erase them."""
        config = {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "parameters": {
                "DEFAULT_TIMEOUT": "30",
                "TARGET_NAMESPACE": "benchmark",
            },
        }
        config_file = str(tmp_path / "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        # Override TARGET_NAMESPACE, add NEW_PARAM, keep DEFAULT_TIMEOUT
        result = read_config_from_file(
            config_file,
            param=["TARGET_NAMESPACE=prod", "NEW_PARAM=value"],
        )

        assert "DEFAULT_TIMEOUT" in result.parameters
        assert result.parameters["DEFAULT_TIMEOUT"].value == "30"

        assert "TARGET_NAMESPACE" in result.parameters
        assert result.parameters["TARGET_NAMESPACE"].value == "prod"  # Overridden

        assert "NEW_PARAM" in result.parameters
        assert result.parameters["NEW_PARAM"].value == "value"  # Added

    def test_elastic_null_values_are_not_stringified_with_params(self, tmp_path):
        """Explicit elastic nulls should remain null so validation catches them."""
        config = {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "elastic": {
                "server": "https://$ES_HOST",
                "username": None,
            },
        }
        config_file = str(tmp_path / "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        with pytest.raises(ValidationError):
            read_config_from_file(config_file, param=["ES_HOST=example.com"])


class TestReadConfigValidation:
    def test_read_config_empty_file(self, tmp_path):
        """Empty YAML file should raise ValidationError from Pydantic (missing required fields)"""
        config_file = str(tmp_path / "empty.yaml")
        with open(config_file, "w") as f:
            f.write("")
        with pytest.raises(ValidationError):
            read_config_from_file(config_file)

    def test_read_config_non_dict_root(self, tmp_path):
        """YAML with non-dict root (e.g. list) should raise ValueError"""
        config_file = str(tmp_path / "list.yaml")
        with open(config_file, "w") as f:
            f.write("- item1\n- item2")
        with pytest.raises(ValueError, match="must be a mapping"):
            read_config_from_file(config_file)

    def test_read_config_string_root(self, tmp_path):
        """YAML with string root should raise ValueError"""
        config_file = str(tmp_path / "string.yaml")
        with open(config_file, "w") as f:
            f.write("just a string")
        with pytest.raises(ValueError, match="must be a mapping"):
            read_config_from_file(config_file)


KUBECONFIG = "/tmp/kubeconfig"


class TestMergeComponents:
    def test_new_namespace_is_appended(self):
        existing = ClusterComponents(namespaces=[Namespace(name="a")])
        discovered = ClusterComponents(
            namespaces=[Namespace(name="a"), Namespace(name="b")]
        )
        merged = merge_components(existing, discovered)
        assert [n.name for n in merged.namespaces] == ["a", "b"]

    def test_new_pod_added_to_existing_namespace(self):
        existing = ClusterComponents(
            namespaces=[Namespace(name="a", pods=[Pod(name="p1")])]
        )
        discovered = ClusterComponents(
            namespaces=[Namespace(name="a", pods=[Pod(name="p1"), Pod(name="p2")])]
        )
        merged = merge_components(existing, discovered)
        assert [p.name for p in merged.namespaces[0].pods] == ["p1", "p2"]

    def test_duplicate_names_not_doubled(self):
        existing = ClusterComponents(
            namespaces=[Namespace(name="a", pods=[Pod(name="p1")])]
        )
        discovered = ClusterComponents(
            namespaces=[Namespace(name="a", pods=[Pod(name="p1")])]
        )
        merged = merge_components(existing, discovered)
        assert len(merged.namespaces) == 1
        assert len(merged.namespaces[0].pods) == 1

    def test_existing_disabled_flag_survives(self):
        existing = ClusterComponents(
            namespaces=[Namespace(name="a", pods=[Pod(name="p1", disabled=True)])]
        )
        discovered = ClusterComponents(
            namespaces=[Namespace(name="a", pods=[Pod(name="p1")])]
        )
        merged = merge_components(existing, discovered)
        assert merged.namespaces[0].pods[0].disabled is True

    def test_nodes_union_by_name(self):
        existing = ClusterComponents(nodes=[Node(name="n1")])
        discovered = ClusterComponents(nodes=[Node(name="n1"), Node(name="n2")])
        merged = merge_components(existing, discovered)
        assert [n.name for n in merged.nodes] == ["n1", "n2"]


def _write_existing(path, components):
    """Write a valid config file via the krkn-ai template."""
    data = components.model_dump(mode="json", warnings="none", exclude_defaults=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(create_krkn_ai_template(KUBECONFIG, data))


class TestSaveDiscovery:
    def test_skip_writes_when_file_absent(self, tmp_path):
        """Skip strategy creates file if it doesn't exist."""
        path = str(tmp_path / "krkn-ai.yaml")
        components = ClusterComponents(namespaces=[Namespace(name="shop")])
        save_discovery(path, "skip", components, KUBECONFIG)
        data = yaml.safe_load(open(path))
        names = [n["name"] for n in data["cluster_components"]["namespaces"]]
        assert "shop" in names

    def test_skip_leaves_existing_file_unchanged(self, tmp_path):
        """Skip strategy does nothing if file already exists."""
        path = str(tmp_path / "krkn-ai.yaml")
        with open(path, "w") as f:
            f.write("original: true\n")
        components = ClusterComponents(namespaces=[Namespace(name="shop")])
        save_discovery(path, "skip", components, KUBECONFIG)
        assert open(path).read() == "original: true\n"

    def test_overwrite_replaces_file(self, tmp_path):
        """Overwrite strategy replaces entire file with fresh discovery."""
        path = str(tmp_path / "krkn-ai.yaml")
        with open(path, "w") as f:
            f.write("original: true\n")
        components = ClusterComponents(namespaces=[Namespace(name="shop")])
        save_discovery(path, "overwrite", components, KUBECONFIG)
        data = yaml.safe_load(open(path))
        assert "original" not in data
        names = [n["name"] for n in data["cluster_components"]["namespaces"]]
        assert "shop" in names

    def test_merge_preserves_component_edits_and_adds_new(self, tmp_path):
        """Preserves per-component edits and adds new components on merge."""
        path = str(tmp_path / "krkn-ai.yaml")
        existing = ClusterComponents(
            namespaces=[Namespace(name="shop", pods=[Pod(name="redis", disabled=True)])]
        )
        _write_existing(path, existing)
        discovered = ClusterComponents(
            namespaces=[
                Namespace(name="shop", pods=[Pod(name="redis"), Pod(name="cart")]),
                Namespace(name="pay", pods=[Pod(name="ledger")]),
            ]
        )
        save_discovery(path, "merge", discovered, KUBECONFIG)
        data = yaml.safe_load(open(path))
        shop = next(
            n for n in data["cluster_components"]["namespaces"] if n["name"] == "shop"
        )
        redis = next(p for p in shop["pods"] if p["name"] == "redis")
        assert redis["disabled"] is True
        names = [n["name"] for n in data["cluster_components"]["namespaces"]]
        assert "pay" in names

    def test_merge_preserves_non_component_edits(self, tmp_path):
        """Merge keeps non-component edits."""
        path = str(tmp_path / "krkn-ai.yaml")
        existing = ClusterComponents(namespaces=[Namespace(name="shop")])
        _write_existing(path, existing)
        # edit a few non-component fields
        doc = yaml.safe_load(open(path))
        doc["generations"] = 50
        doc["population_size"] = 30
        doc["fitness_function"]["query"] = "sum(my_custom_metric)"
        doc["scenario"]["pvc-scenarios"]["enable"] = True
        with open(path, "w") as f:
            yaml.safe_dump(doc, f)

        discovered = ClusterComponents(namespaces=[Namespace(name="pay")])
        save_discovery(path, "merge", discovered, KUBECONFIG)

        result = yaml.safe_load(open(path))
        # edits survived
        assert result["generations"] == 50
        assert result["population_size"] == 30
        assert result["fitness_function"]["query"] == "sum(my_custom_metric)"
        assert result["scenario"]["pvc-scenarios"]["enable"] is True
        # new component added
        names = [n["name"] for n in result["cluster_components"]["namespaces"]]
        assert "pay" in names and "shop" in names

    def test_merge_keeps_secrets_and_parameters(self, tmp_path):
        """Merge keeps elastic.password and parameters."""
        path = str(tmp_path / "krkn-ai.yaml")
        _write_existing(path, ClusterComponents(namespaces=[Namespace(name="shop")]))
        doc = yaml.safe_load(open(path))
        doc["elastic"] = {"enable": True, "server": "https://es", "password": "s3cret"}
        doc["parameters"] = {"TOKEN": {"value": "abc", "is_private": False}}
        with open(path, "w") as f:
            yaml.safe_dump(doc, f)

        discovered = ClusterComponents(namespaces=[Namespace(name="pay")])
        save_discovery(path, "merge", discovered, KUBECONFIG)

        result = yaml.safe_load(open(path))
        assert result["elastic"]["password"] == "s3cret"  # not dropped
        assert result["parameters"]["TOKEN"]["value"] == "abc"  # not collapsed
        names = [n["name"] for n in result["cluster_components"]["namespaces"]]
        assert "pay" in names and "shop" in names

    def test_merge_safe_to_repeat(self, tmp_path):
        """Running merge twice produces the same result."""
        path = str(tmp_path / "krkn-ai.yaml")
        existing = ClusterComponents(
            namespaces=[Namespace(name="shop", pods=[Pod(name="redis")])]
        )
        _write_existing(path, existing)
        discovered = ClusterComponents(
            namespaces=[Namespace(name="shop", pods=[Pod(name="redis")])]
        )
        save_discovery(path, "merge", discovered, KUBECONFIG)
        first = open(path).read()
        save_discovery(path, "merge", discovered, KUBECONFIG)
        assert open(path).read() == first

    def test_merge_leaves_invalid_file_unchanged(self, tmp_path):
        """Invalid existing file is left unchanged on merge."""
        path = str(tmp_path / "krkn-ai.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not: [a, valid, krkn-ai, config\n")  # malformed YAML
        original = open(path).read()
        discovered = ClusterComponents(namespaces=[Namespace(name="shop")])

        with patch("krkn_ai.utils.fs.logger") as mock_logger:
            save_discovery(path, "merge", discovered, KUBECONFIG)
            assert mock_logger.warning.called
        assert open(path).read() == original

    def test_skip_and_overwrite_emit_warnings(self, tmp_path):
        """Skip and overwrite both warn the user about the existing file."""
        path = str(tmp_path / "krkn-ai.yaml")
        with open(path, "w") as f:
            f.write("original: true\n")
        components = ClusterComponents(namespaces=[Namespace(name="shop")])

        with patch("krkn_ai.utils.fs.logger") as mock_logger:
            save_discovery(path, "skip", components, KUBECONFIG)
            assert mock_logger.warning.called

        with patch("krkn_ai.utils.fs.logger") as mock_logger:
            save_discovery(path, "overwrite", components, KUBECONFIG)
            assert mock_logger.warning.called

    def test_merge_writes_fresh_when_file_absent(self, tmp_path):
        """Merge on a missing file falls back to a fresh write."""
        path = str(tmp_path / "krkn-ai.yaml")
        components = ClusterComponents(namespaces=[Namespace(name="shop")])
        save_discovery(path, "merge", components, KUBECONFIG)
        data = yaml.safe_load(open(path))
        names = [n["name"] for n in data["cluster_components"]["namespaces"]]
        assert "shop" in names

    def test_overwrite_applies_scenario_enables(self, tmp_path):
        """Overwrite applies scenario enables."""
        path = str(tmp_path / "krkn-ai.yaml")
        with open(path, "w") as f:
            f.write("original: true\n")
        components = ClusterComponents(namespaces=[Namespace(name="shop")])
        from krkn_ai.models.scenario.factory import scenario_specs

        enables = {n: n == "pvc_scenarios" for n, _ in scenario_specs}
        save_discovery(
            path,
            "overwrite",
            components,
            KUBECONFIG,
            scenario_enables=enables,
        )
        data = yaml.safe_load(open(path))
        assert data["scenario"]["pvc-scenarios"]["enable"] is True
        assert data["scenario"]["pod-scenarios"]["enable"] is False

    def test_overwrite_without_enables_disables_all(self, tmp_path):
        """No scenario_enables disables all scenarios."""
        path = str(tmp_path / "krkn-ai.yaml")
        components = ClusterComponents(namespaces=[Namespace(name="shop")])
        save_discovery(path, "overwrite", components, KUBECONFIG)
        data = yaml.safe_load(open(path))
        assert data["scenario"]["pod-scenarios"]["enable"] is False
        assert data["scenario"]["pvc-scenarios"]["enable"] is False

    def test_merge_existing_ignores_scenario_enables(self, tmp_path):
        """Merge keeps the user's scenario flags."""
        path = str(tmp_path / "krkn-ai.yaml")
        _write_existing(path, ClusterComponents(namespaces=[Namespace(name="shop")]))
        discovered = ClusterComponents(namespaces=[Namespace(name="pay")])
        from krkn_ai.models.scenario.factory import scenario_specs

        enables = {n: n == "pvc_scenarios" for n, _ in scenario_specs}
        save_discovery(
            path,
            "merge",
            discovered,
            KUBECONFIG,
            scenario_enables=enables,
        )
        data = yaml.safe_load(open(path))
        assert data["scenario"]["pvc-scenarios"]["enable"] is False
        assert data["scenario"]["pod-scenarios"]["enable"] is False

    def test_strategy_is_case_insensitive(self, tmp_path):
        """Strategy matching ignores case (e.g. SKIP behaves like skip)."""
        path = str(tmp_path / "krkn-ai.yaml")
        with open(path, "w") as f:
            f.write("original: true\n")
        components = ClusterComponents(namespaces=[Namespace(name="shop")])
        save_discovery(path, "SKIP", components, KUBECONFIG)
        assert open(path).read() == "original: true\n"

    def test_merge_leaves_invalid_config_unchanged(self, tmp_path):
        """Valid YAML with wrong schema is left unchanged on merge."""
        path = str(tmp_path / "krkn-ai.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write("some_field: value\n")  # valid YAML, not a valid krkn-ai config
        original = open(path).read()
        discovered = ClusterComponents(namespaces=[Namespace(name="shop")])

        with patch("krkn_ai.utils.fs.logger") as mock_logger:
            save_discovery(path, "merge", discovered, KUBECONFIG)
            assert mock_logger.warning.called
        assert open(path).read() == original

    def test_overwrite_writes_when_file_absent(self, tmp_path):
        """Overwrite strategy creates a fresh file when none exists."""
        path = str(tmp_path / "krkn-ai.yaml")
        components = ClusterComponents(namespaces=[Namespace(name="shop")])
        save_discovery(path, "overwrite", components, KUBECONFIG)
        data = yaml.safe_load(open(path))
        names = [n["name"] for n in data["cluster_components"]["namespaces"]]
        assert "shop" in names
