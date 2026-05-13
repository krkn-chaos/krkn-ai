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
        # No LoadBalancer services
        cluster_manager.core_api.list_namespaced_service.return_value.items = []

        namespaces = [Namespace(name="default")]
        urls = cluster_manager.discover_health_check_urls(namespaces)

        assert len(urls) == 2
        names = {u["name"] for u in urls}
        assert "web-app.example.com-root" in names
        assert "api-route" in names


class TestLoadBalancerDiscovery:
    """Test LoadBalancer Service URL discovery."""

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
            with patch("krkn_ai.utils.cluster_manager.NetworkingV1Api"):
                mgr = ClusterManager(kubeconfig="/tmp/test-kubeconfig")
                return mgr

    def _make_lb_service(self, name, ingress_entries, ports=None):
        svc = Mock()
        svc.metadata.name = name
        svc.spec.type = "LoadBalancer"
        svc.spec.ports = ports or []
        if ingress_entries is not None:
            svc.status.load_balancer.ingress = ingress_entries
        else:
            svc.status.load_balancer.ingress = None
        return svc

    def _make_ingress_entry(self, ip=None, hostname=None):
        entry = Mock()
        entry.ip = ip
        entry.hostname = hostname
        return entry

    def _make_port(self, port):
        p = Mock()
        p.port = port
        return p

    def test_discover_loadbalancer_urls_with_ip(self, cluster_manager):
        """Test LoadBalancer with IP address."""
        svc = self._make_lb_service(
            "my-lb",
            [self._make_ingress_entry(ip="1.2.3.4")],
            ports=[self._make_port(80)],
        )
        cluster_manager.core_api.list_namespaced_service.return_value.items = [svc]

        urls = cluster_manager._discover_loadbalancer_urls("default")

        assert len(urls) == 1
        assert urls[0] == {"name": "my-lb", "url": "http://1.2.3.4"}

    def test_discover_loadbalancer_urls_with_hostname(self, cluster_manager):
        """Test LoadBalancer with hostname."""
        svc = self._make_lb_service(
            "aws-lb",
            [self._make_ingress_entry(hostname="abc.elb.amazonaws.com")],
            ports=[self._make_port(80)],
        )
        cluster_manager.core_api.list_namespaced_service.return_value.items = [svc]

        urls = cluster_manager._discover_loadbalancer_urls("default")

        assert len(urls) == 1
        assert urls[0] == {"name": "aws-lb", "url": "http://abc.elb.amazonaws.com"}

    def test_discover_loadbalancer_urls_https_on_port_443(self, cluster_manager):
        """Test that port 443 triggers https scheme."""
        svc = self._make_lb_service(
            "secure-lb",
            [self._make_ingress_entry(ip="10.0.0.1")],
            ports=[self._make_port(443)],
        )
        cluster_manager.core_api.list_namespaced_service.return_value.items = [svc]

        urls = cluster_manager._discover_loadbalancer_urls("default")

        assert len(urls) == 1
        assert urls[0] == {"name": "secure-lb", "url": "https://10.0.0.1"}

    def test_discover_loadbalancer_urls_empty_status(self, cluster_manager):
        """Test LoadBalancer with no ingress status returns nothing."""
        svc = self._make_lb_service("pending-lb", None)
        cluster_manager.core_api.list_namespaced_service.return_value.items = [svc]

        urls = cluster_manager._discover_loadbalancer_urls("default")

        assert urls == []

    def test_discover_loadbalancer_urls_api_error(self, cluster_manager):
        """Test that API errors return empty list with warning."""
        cluster_manager.core_api.list_namespaced_service.side_effect = Exception(
            "forbidden"
        )

        urls = cluster_manager._discover_loadbalancer_urls("default")

        assert urls == []


class TestProbeHealthCheckUrls:
    """Tests for probe_health_check_urls reachability filtering."""

    @pytest.fixture
    def cluster_manager(self):
        with patch("krkn_ai.utils.cluster_manager.KrknKubernetes"):
            return ClusterManager("/tmp/fake-kubeconfig")

    def test_reachable_url_kept(self, cluster_manager):
        """URLs that respond (any HTTP status) are kept."""
        import urllib.error

        urls = [{"name": "app", "url": "http://10.0.0.1/health"}]
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url=None, code=200, msg="OK", hdrs=None, fp=None
            ),
        ):
            result = cluster_manager.probe_health_check_urls(urls, timeout=1)
        assert result == urls

    def test_unreachable_url_excluded(self, cluster_manager):
        """URLs that time out or refuse connection are excluded."""
        urls = [{"name": "dead", "url": "http://192.0.2.1/health"}]
        with patch("urllib.request.urlopen", side_effect=OSError("timed out")):
            result = cluster_manager.probe_health_check_urls(urls, timeout=1)
        assert result == []

    def test_mixed_urls_filtered(self, cluster_manager):
        """Only reachable URLs are returned from a mixed list."""
        import urllib.error

        urls = [
            {"name": "ok", "url": "http://10.0.0.1/"},
            {"name": "dead", "url": "http://192.0.2.1/"},
        ]

        def side_effect(req, timeout):
            if "192.0.2.1" in req.full_url:
                raise OSError("refused")
            raise urllib.error.HTTPError(
                url=None, code=404, msg="Not Found", hdrs=None, fp=None
            )

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = cluster_manager.probe_health_check_urls(urls, timeout=1)
        assert len(result) == 1
        assert result[0]["name"] == "ok"

    def test_empty_list_returns_empty(self, cluster_manager):
        """Empty input returns empty output without making any requests."""
        with patch("urllib.request.urlopen") as mock_open:
            result = cluster_manager.probe_health_check_urls([], timeout=1)
        assert result == []
        mock_open.assert_not_called()
