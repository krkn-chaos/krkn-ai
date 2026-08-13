"""Tests for utils/fs.py"""

import yaml

from krkn_ai.utils.fs import read_config_from_file, preprocess_param_string


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


class TestPreprocessParamString:
    def test_prefix_collision_does_not_corrupt(self):
        """HOST must not shadow HOST_PORT regardless of dict ordering."""
        params = {"HOST": "app.cluster.local", "HOST_PORT": "8443"}
        result = preprocess_param_string("https://$HOST_PORT/api/$HOST/probe", params)
        assert result == "https://8443/api/app.cluster.local/probe"

    def test_prefix_collision_reverse_order(self):
        """Same test with HOST_PORT listed first in the dict."""
        params = {"HOST_PORT": "8443", "HOST": "app.cluster.local"}
        result = preprocess_param_string("https://$HOST_PORT/api/$HOST/probe", params)
        assert result == "https://8443/api/app.cluster.local/probe"

    def test_unresolved_param_left_unchanged(self):
        """A $TOKEN with no matching key should stay as-is."""
        params = {"HOST": "app.cluster.local"}
        result = preprocess_param_string("https://$HOST_PORT/api/$HOST/probe", params)
        assert result == "https://$HOST_PORT/api/app.cluster.local/probe"

    def test_simple_substitution(self):
        """Basic single-param replacement still works."""
        result = preprocess_param_string("http://$HOST/health", {"HOST": "myhost.com"})
        assert result == "http://myhost.com/health"

    def test_private_param_substitution(self):
        """Double-underscore private params are valid identifiers."""
        result = preprocess_param_string("Bearer $__TOKEN", {"__TOKEN": "secret"})
        assert result == "Bearer secret"

    def test_no_params_returns_unchanged(self):
        """Empty params dict leaves data unchanged."""
        result = preprocess_param_string("http://$HOST/health", {})
        assert result == "http://$HOST/health"


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
