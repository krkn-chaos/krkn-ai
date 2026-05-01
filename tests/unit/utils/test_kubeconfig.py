"""
Unit tests for ``krkn_ai.utils.kubeconfig``.
"""

import pytest
import yaml

from krkn_ai.models.custom_errors import KubeconfigValidationError
from krkn_ai.utils.kubeconfig import (
    _find_path_based_credentials,
    validate_kubeconfig_for_container_use,
)

# A kubeconfig that uses embedded base64 credentials — works inside containers.
EMBEDDED_KUBECONFIG = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [
        {
            "name": "test",
            "cluster": {
                "server": "https://127.0.0.1:6443",
                "certificate-authority-data": "LS0tLS1CRUdJTi==",
            },
        }
    ],
    "users": [
        {
            "name": "test-user",
            "user": {
                "client-certificate-data": "LS0tLS1CRUdJTi==",
                "client-key-data": "LS0tLS1CRUdJTi==",
            },
        }
    ],
    "contexts": [{"name": "test", "context": {"cluster": "test", "user": "test-user"}}],
    "current-context": "test",
}

# A typical minikube-generated kubeconfig — references credentials by host path.
PATH_BASED_KUBECONFIG = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [
        {
            "name": "minikube",
            "cluster": {
                "server": "https://192.168.49.2:8443",
                "certificate-authority": "/root/.minikube/ca.crt",
            },
        }
    ],
    "users": [
        {
            "name": "minikube",
            "user": {
                "client-certificate": "/root/.minikube/profiles/minikube/client.crt",
                "client-key": "/root/.minikube/profiles/minikube/client.key",
            },
        }
    ],
    "contexts": [
        {"name": "minikube", "context": {"cluster": "minikube", "user": "minikube"}}
    ],
    "current-context": "minikube",
}


class TestFindPathBasedCredentials:
    """Unit tests for the internal ``_find_path_based_credentials`` helper."""

    def test_embedded_kubeconfig_returns_empty(self):
        assert _find_path_based_credentials(EMBEDDED_KUBECONFIG) == []

    def test_path_based_kubeconfig_finds_all_three(self):
        issues = _find_path_based_credentials(PATH_BASED_KUBECONFIG)
        locations = {loc for loc, _ in issues}
        assert "clusters[0].cluster.certificate-authority" in locations
        assert "users[0].user.client-certificate" in locations
        assert "users[0].user.client-key" in locations
        assert len(issues) == 3

    def test_empty_config_returns_empty(self):
        assert _find_path_based_credentials({}) == []

    def test_missing_clusters_key(self):
        assert _find_path_based_credentials({"users": []}) == []

    def test_missing_users_key(self):
        assert _find_path_based_credentials({"clusters": []}) == []

    def test_clusters_value_is_none(self):
        # PyYAML can produce {"clusters": None} for `clusters:` with no children.
        assert _find_path_based_credentials({"clusters": None, "users": None}) == []

    def test_cluster_block_is_none(self):
        # PyYAML can produce {"cluster": None} for an empty cluster entry.
        config = {"clusters": [{"name": "c", "cluster": None}], "users": []}
        assert _find_path_based_credentials(config) == []

    def test_locations_use_yaml_style_indices(self):
        # Two clusters, second one has the path-based key.
        config = {
            "clusters": [
                {"name": "c0", "cluster": {"certificate-authority-data": "ok"}},
                {"name": "c1", "cluster": {"certificate-authority": "/etc/ca"}},
            ],
            "users": [],
        }
        issues = _find_path_based_credentials(config)
        assert issues == [("clusters[1].cluster.certificate-authority", "/etc/ca")]


class TestValidateKubeconfigForContainerUse:
    """Tests for the public ``validate_kubeconfig_for_container_use`` entrypoint."""

    def test_embedded_kubeconfig_passes_silently(self, tmp_path):
        path = tmp_path / "kubeconfig.yaml"
        path.write_text(yaml.dump(EMBEDDED_KUBECONFIG), encoding="utf-8")
        # Should return None without raising.
        assert validate_kubeconfig_for_container_use(str(path)) is None

    def test_path_based_kubeconfig_raises_with_actionable_message(self, tmp_path):
        path = tmp_path / "kubeconfig.yaml"
        path.write_text(yaml.dump(PATH_BASED_KUBECONFIG), encoding="utf-8")

        with pytest.raises(KubeconfigValidationError) as exc_info:
            validate_kubeconfig_for_container_use(str(path))

        msg = str(exc_info.value)

        # The message names every problematic location so the user can find them.
        assert "clusters[0].cluster.certificate-authority" in msg
        assert "users[0].user.client-certificate" in msg
        assert "users[0].user.client-key" in msg

        # The actual offending values are included so the user can grep their kubeconfig.
        assert "/root/.minikube/ca.crt" in msg

        # The actionable fix command is included verbatim.
        assert "kubectl config view" in msg
        assert "--minify --flatten --raw" in msg

    def test_missing_file_raises_with_clear_error(self, tmp_path):
        with pytest.raises(KubeconfigValidationError, match="not found"):
            validate_kubeconfig_for_container_use(str(tmp_path / "does-not-exist.yaml"))

    def test_invalid_yaml_raises_with_clear_error(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("not: valid: yaml: [unclosed", encoding="utf-8")
        with pytest.raises(KubeconfigValidationError, match="not valid YAML"):
            validate_kubeconfig_for_container_use(str(path))

    def test_non_mapping_yaml_raises_with_clear_error(self, tmp_path):
        path = tmp_path / "list.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(KubeconfigValidationError, match="not a valid YAML mapping"):
            validate_kubeconfig_for_container_use(str(path))

    def test_partially_path_based_only_problem_user_reported(self, tmp_path):
        # One user has embedded credentials (good); a second user has path-based (bad).
        # Only the path-based one should appear in the error.
        config = {
            "clusters": [
                {"name": "c1", "cluster": {"certificate-authority-data": "abc"}},
            ],
            "users": [
                {
                    "name": "u1",
                    "user": {
                        "client-certificate-data": "abc",
                        "client-key-data": "def",
                    },
                },
                {"name": "u2", "user": {"client-certificate": "/path/to/cert"}},
            ],
        }
        path = tmp_path / "mixed.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")

        with pytest.raises(KubeconfigValidationError) as exc_info:
            validate_kubeconfig_for_container_use(str(path))

        msg = str(exc_info.value)
        assert "users[1].user.client-certificate" in msg
        # The fully-embedded user/cluster shouldn't be mentioned.
        assert "users[0]" not in msg
        assert "clusters[0]" not in msg
