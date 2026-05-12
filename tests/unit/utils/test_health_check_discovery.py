"""
Unit tests for Ingress and OpenShift Route health check URL discovery.
"""

import pytest
from unittest.mock import Mock, patch

from krkn_ai.utils.cluster_manager import ClusterManager
from krkn_ai.models.cluster_components import Namespace


class TestHealthCheckDiscovery:
    """Test health check URL discovery from Ingresses and Routes."""

    @pytest.fixture
    def mock_krkn_k8s(self):
        mock_k8s = Mock()
        mock_k8s.apps_api = Mock()
        mock_k8s.api_client = Mock()
        mock_k8s.cli = Mock()
        mock_k8s.custom_object_client = Mock()
        mock_k8s.list_namespaces = Mock(return_value=["default"])
        return mock_k8s

    @pytest.fixture
    def cluster_manager(self, mock_krkn_k8s):
        with patch(
            "krkn_ai.utils.cluster_manager.KrknKubernetes",
            return_value=mock_krkn_k8s,
        ):
            with patch(
                "krkn_ai.utils.cluster_manager.NetworkingV1Api"
            ) as mock_net_api_cls:
                mock_net_api = Mock()
                mock_net_api_cls.return_value = mock_net_api
                mgr = ClusterManager(kubeconfig="/tmp/test-kubeconfig")
                mgr.networking_api = mock_net_api
                return mgr

    def _make_ingress(self, name, rules, tls=None):
        ing = Mock()
        ing.metadata.name = name
        ing.spec.tls = tls
        ing.spec.rules = rules
        return ing

    def _make_rule(self, host, paths=None):
        rule = Mock()
        rule.host = host
        if paths is not None:
            rule.http = Mock()
            rule.http.paths = paths
        else:
            rule.http = None
        return rule

    def _make_path(self, path):
        p = Mock()
        p.path = path
        return p

    def test_discover_ingress_urls_extracts_host_and_path(self, cluster_manager):
        """Test that Ingress hosts and paths are correctly extracted as URLs."""
        rule = self._make_rule("app.example.com", [self._make_path("/api")])
        ingress = self._make_ingress("my-ingress", [rule])
        cluster_manager.networking_api.list_namespaced_ingress.return_value.items = [
            ingress
        ]

        urls = cluster_manager._discover_ingress_urls("default")

        assert len(urls) == 1
        assert urls[0]["name"] == "my-ingress-app.example.com-api"
        assert urls[0]["url"] == "http://app.example.com/api"

    def test_discover_ingress_urls_uses_https_for_tls_hosts(self, cluster_manager):
        """Test that TLS-configured hosts get https scheme."""
        rule = self._make_rule("secure.example.com", [self._make_path("/")])
        tls = Mock()
        tls.hosts = ["secure.example.com"]
        ingress = self._make_ingress("tls-ingress", [rule], tls=[tls])
        cluster_manager.networking_api.list_namespaced_ingress.return_value.items = [
            ingress
        ]

        urls = cluster_manager._discover_ingress_urls("default")

        assert len(urls) == 1
        assert urls[0]["url"] == "https://secure.example.com/"

    def test_discover_ingress_urls_handles_no_paths(self, cluster_manager):
        """Test Ingress rule with no HTTP paths defaults to /."""
        rule = self._make_rule("bare.example.com")
        ingress = self._make_ingress("bare-ingress", [rule])
        cluster_manager.networking_api.list_namespaced_ingress.return_value.items = [
            ingress
        ]

        urls = cluster_manager._discover_ingress_urls("default")

        assert len(urls) == 1
        assert urls[0]["url"] == "http://bare.example.com/"

    def test_discover_ingress_urls_skips_rules_without_host(self, cluster_manager):
        """Test that rules without a host are skipped."""
        rule = self._make_rule(None, [self._make_path("/")])
        ingress = self._make_ingress("no-host", [rule])
        cluster_manager.networking_api.list_namespaced_ingress.return_value.items = [
            ingress
        ]

        urls = cluster_manager._discover_ingress_urls("default")

        assert len(urls) == 0

    def test_discover_ingress_urls_handles_api_error_gracefully(self, cluster_manager):
        """Test that API errors return empty list."""
        cluster_manager.networking_api.list_namespaced_ingress.side_effect = Exception(
            "forbidden"
        )

        urls = cluster_manager._discover_ingress_urls("default")

        assert urls == []

    def test_discover_route_urls_extracts_openshift_routes(self, cluster_manager):
        """Test that OpenShift Routes are discovered correctly."""
        cluster_manager.custom_obj_api.list_namespaced_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "my-route"},
                    "spec": {
                        "host": "route.apps.example.com",
                        "path": "/health",
                        "tls": {"termination": "edge"},
                    },
                }
            ]
        }

        urls = cluster_manager._discover_route_urls("default")

        assert len(urls) == 1
        assert urls[0]["name"] == "my-route"
        assert urls[0]["url"] == "https://route.apps.example.com/health"

    def test_discover_route_urls_uses_http_when_no_tls(self, cluster_manager):
        """Test that Routes without TLS use http scheme."""
        cluster_manager.custom_obj_api.list_namespaced_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "plain-route"},
                    "spec": {"host": "plain.apps.example.com"},
                }
            ]
        }

        urls = cluster_manager._discover_route_urls("default")

        assert len(urls) == 1
        assert urls[0]["url"] == "http://plain.apps.example.com/"

    def test_discover_route_urls_graceful_when_crd_absent(self, cluster_manager):
        """Test that missing Route CRD returns empty list without error."""
        cluster_manager.custom_obj_api.list_namespaced_custom_object.side_effect = (
            Exception("the server doesn't have a resource type 'routes'")
        )

        urls = cluster_manager._discover_route_urls("default")

        assert urls == []

    def test_discover_health_check_urls_combines_ingresses_and_routes(
        self, cluster_manager
    ):
        """Test that discover_health_check_urls aggregates from all namespaces."""
        rule = self._make_rule("app.example.com", [self._make_path("/")])
        ingress = self._make_ingress("web", [rule])
        cluster_manager.networking_api.list_namespaced_ingress.return_value.items = [
            ingress
        ]
        cluster_manager.custom_obj_api.list_namespaced_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "api-route"},
                    "spec": {"host": "api.apps.example.com", "tls": {}},
                }
            ]
        }

        namespaces = [Namespace(name="default")]
        urls = cluster_manager.discover_health_check_urls(namespaces)

        assert len(urls) == 2
        names = {u["name"] for u in urls}
        assert "web-app.example.com-root" in names
        assert "api-route" in names
