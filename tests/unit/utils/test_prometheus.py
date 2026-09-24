"""
Unit tests for Prometheus utility functions and client creation logic using Kubernetes Python client.
"""

import os
import pytest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from krkn_ai.utils.prometheus import is_openshift, create_prometheus_client
from krkn_ai.models.custom_errors import PrometheusConnectionError


def _ingress(name, host, tls=False, backend_service=None):
    """Build a minimal V1Ingress-like object for discovery tests."""
    http = None
    if backend_service:
        http = SimpleNamespace(
            paths=[
                SimpleNamespace(
                    backend=SimpleNamespace(
                        service=SimpleNamespace(name=backend_service)
                    )
                )
            ]
        )
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(
            tls=[SimpleNamespace()] if tls else None,
            rules=[SimpleNamespace(host=host, http=http)],
        ),
    )


def _service(name, hostname=None, ip=None, port=9090, svc_type="LoadBalancer"):
    """Build a minimal V1Service-like object for discovery tests."""
    lb_ingress = [SimpleNamespace(hostname=hostname, ip=ip)] if (hostname or ip) else []
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(
            type=svc_type,
            ports=[SimpleNamespace(port=port)] if port else [],
        ),
        status=SimpleNamespace(load_balancer=SimpleNamespace(ingress=lb_ingress)),
    )


class TestPrometheusUtils:
    """Tests for Prometheus utility functions."""

    @patch("krkn_ai.utils.prometheus.config.load_kube_config")
    @patch("krkn_ai.utils.prometheus.client.CustomObjectsApi")
    def test_is_openshift_positive(self, mock_api_class, mock_load):
        """Should return True when clusterversions resource is found."""
        mock_api = mock_api_class.return_value
        mock_api.list_cluster_custom_object.return_value = {"items": []}
        assert is_openshift("/tmp/test-kubeconfig") is True
        mock_load.assert_called_with(config_file="/tmp/test-kubeconfig")

    @patch("krkn_ai.utils.prometheus.config.load_kube_config")
    @patch("krkn_ai.utils.prometheus.client.CustomObjectsApi")
    def test_is_openshift_negative(self, mock_api_class, _):
        """Should return False when clusterversions resource is missing or access denied."""
        mock_api = mock_api_class.return_value
        mock_api.list_cluster_custom_object.side_effect = Exception("Not OpenShift")
        assert is_openshift("/tmp/test-kubeconfig") is False

    @patch("krkn_ai.utils.prometheus.KrknPrometheus")
    def test_create_client_from_env_vars(self, mock_prom_class):
        """Should prioritize PROMETHEUS_URL and PROMETHEUS_TOKEN from environment."""
        env = {
            "PROMETHEUS_URL": "prometheus.example.com",
            "PROMETHEUS_TOKEN": "secret-token",
        }
        with patch.dict(os.environ, env):
            mock_client = Mock()
            mock_client.process_query.return_value = None
            mock_prom_class.return_value = mock_client

            client = create_prometheus_client("/tmp/test-kubeconfig")

            mock_prom_class.assert_called_once_with(
                "https://prometheus.example.com", "secret-token"
            )
            assert client == mock_client

    @patch("krkn_ai.utils.prometheus.is_openshift", return_value=True)
    @patch("krkn_ai.utils.prometheus.config.load_kube_config")
    @patch("krkn_ai.utils.prometheus.client.CustomObjectsApi")
    @patch("krkn_ai.utils.prometheus.config.new_client_from_config")
    @patch("krkn_ai.utils.prometheus.KrknPrometheus")
    def test_create_client_autodiscovery_openshift(
        self, mock_prom_class, mock_new_client, mock_api_class, _, __
    ):
        """Should auto-discover URL and token on OpenShift clusters using Python client."""
        # Mock Route discovery
        mock_api = mock_api_class.return_value
        mock_api.list_namespaced_custom_object.return_value = {
            "items": [{"spec": {"host": "thanos-query.apps.cluster.com"}}]
        }

        # Mock Token extraction
        mock_api_client = mock_new_client.return_value
        mock_api_client.configuration.api_key = {"authorization": "Bearer k8s-token"}

        with patch.dict(os.environ, {}, clear=True):
            mock_client = Mock()
            mock_client.process_query.return_value = None
            mock_prom_class.return_value = mock_client

            client = create_prometheus_client("/tmp/test-kubeconfig")

            mock_prom_class.assert_called_once()
            args, _ = mock_prom_class.call_args
            assert args[0] == "https://thanos-query.apps.cluster.com"
            assert args[1] == "k8s-token"
            assert client == mock_client

    @patch("krkn_ai.utils.prometheus.is_openshift", return_value=False)
    def test_create_client_missing_config_vanilla_k8s(self, _):
        """Should raise connection error on vanilla K8s if env vars are missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(PrometheusConnectionError) as exc:
                create_prometheus_client("/tmp/test-kubeconfig")
            assert "Prometheus configuration missing" in str(exc.value)

    @patch("krkn_ai.utils.prometheus.is_openshift", return_value=True)
    @patch("krkn_ai.utils.prometheus.config.load_kube_config")
    @patch("krkn_ai.utils.prometheus.client.CustomObjectsApi")
    def test_create_client_autodiscovery_failure_openshift(self, mock_api_class, _, __):
        """Should raise connection error if discovery fails on OpenShift."""
        mock_api = mock_api_class.return_value
        mock_api.list_namespaced_custom_object.side_effect = Exception("API error")

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(PrometheusConnectionError) as exc:
                create_prometheus_client("/tmp/test-kubeconfig")
            assert "discovery failed on OpenShift" in str(exc.value)

    @patch("krkn_ai.utils.prometheus.is_openshift", return_value=True)
    @patch("krkn_ai.utils.prometheus.config.load_kube_config")
    @patch("krkn_ai.utils.prometheus.client.CustomObjectsApi")
    def test_create_client_malformed_route_openshift(self, mock_api_class, _, __):
        """Should handle empty route lists gracefully on OpenShift."""
        mock_api = mock_api_class.return_value
        mock_api.list_namespaced_custom_object.return_value = {"items": []}

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(PrometheusConnectionError):
                create_prometheus_client("/tmp/test-kubeconfig")

    @patch("krkn_ai.utils.prometheus.KrknPrometheus")
    def test_create_client_connection_test_failure(self, mock_prom_class):
        """Should raise connection error if the connection test (process_query) fails."""
        env = {
            "PROMETHEUS_URL": "http://localhost",
            "PROMETHEUS_TOKEN": "tok",
            "MOCK_FITNESS": "false",
        }
        with patch.dict(os.environ, env):
            mock_client = Mock()
            mock_client.process_query.side_effect = Exception("Auth failed")
            mock_prom_class.return_value = mock_client

            with pytest.raises(PrometheusConnectionError) as exc:
                create_prometheus_client("/tmp/test-kubeconfig")
            assert "Failed to connect to Prometheus" in str(exc.value)

    @patch("krkn_ai.utils.prometheus.KrknPrometheus")
    def test_url_protocol_enforcement(self, mock_prom_class):
        """Should enforce https:// prefix if protocol is missing."""
        env = {"PROMETHEUS_URL": "my-prom", "PROMETHEUS_TOKEN": "tok"}
        with patch.dict(os.environ, env):
            mock_client = Mock()
            mock_prom_class.return_value = mock_client

            create_prometheus_client("/tmp/test-kubeconfig")
            args, _ = mock_prom_class.call_args
            assert args[0] == "https://my-prom"


class TestVanillaPrometheusDiscovery:
    """Auto-discovery of Prometheus on vanilla (non-OpenShift) Kubernetes."""

    @patch("krkn_ai.utils.prometheus.KrknPrometheus")
    @patch("krkn_ai.utils.prometheus.client.CoreV1Api")
    @patch("krkn_ai.utils.prometheus.client.NetworkingV1Api")
    @patch("krkn_ai.utils.prometheus.config.load_kube_config")
    @patch("krkn_ai.utils.prometheus.is_openshift", return_value=False)
    def test_discovers_prometheus_via_ingress(
        self, _ocp, _load, mock_net_cls, mock_core_cls, mock_prom_cls
    ):
        """A Prometheus Ingress with TLS is discovered as an https:// URL."""
        mock_net_cls.return_value.list_namespaced_ingress.return_value = (
            SimpleNamespace(
                items=[_ingress("prometheus-ingress", "prom.example.com", tls=True)]
            )
        )
        with patch.dict(os.environ, {}, clear=True):
            mock_prom_cls.return_value = Mock(process_query=Mock(return_value=None))
            create_prometheus_client("/tmp/test-kubeconfig")
            args, _ = mock_prom_cls.call_args
            assert args[0] == "https://prom.example.com"

    @patch("krkn_ai.utils.prometheus.KrknPrometheus")
    @patch("krkn_ai.utils.prometheus.client.CoreV1Api")
    @patch("krkn_ai.utils.prometheus.client.NetworkingV1Api")
    @patch("krkn_ai.utils.prometheus.config.load_kube_config")
    @patch("krkn_ai.utils.prometheus.is_openshift", return_value=False)
    def test_discovers_prometheus_via_loadbalancer(
        self, _ocp, _load, mock_net_cls, mock_core_cls, mock_prom_cls
    ):
        """A LoadBalancer Service is discovered as http://host:port when no Ingress exists."""
        mock_net_cls.return_value.list_namespaced_ingress.return_value = (
            SimpleNamespace(items=[])
        )
        mock_core_cls.return_value.list_namespaced_service.return_value = (
            SimpleNamespace(
                items=[_service("prometheus-k8s", hostname="lb.example.com", port=9090)]
            )
        )
        with patch.dict(os.environ, {}, clear=True):
            mock_prom_cls.return_value = Mock(process_query=Mock(return_value=None))
            create_prometheus_client("/tmp/test-kubeconfig")
            args, _ = mock_prom_cls.call_args
            assert args[0] == "http://lb.example.com:9090"

    @patch("krkn_ai.utils.prometheus.client.CoreV1Api")
    @patch("krkn_ai.utils.prometheus.client.NetworkingV1Api")
    @patch("krkn_ai.utils.prometheus.config.load_kube_config")
    @patch("krkn_ai.utils.prometheus.is_openshift", return_value=False)
    def test_clusterip_service_is_ignored(
        self, _ocp, _load, mock_net_cls, mock_core_cls
    ):
        """A ClusterIP Service (not externally reachable) is not used for discovery."""
        mock_net_cls.return_value.list_namespaced_ingress.return_value = (
            SimpleNamespace(items=[])
        )
        mock_core_cls.return_value.list_namespaced_service.return_value = (
            SimpleNamespace(
                items=[
                    _service("prometheus-operated", ip="10.0.0.1", svc_type="ClusterIP")
                ]
            )
        )
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(PrometheusConnectionError):
                create_prometheus_client("/tmp/test-kubeconfig")

    @patch("krkn_ai.utils.prometheus.client.CoreV1Api")
    @patch("krkn_ai.utils.prometheus.client.NetworkingV1Api")
    @patch("krkn_ai.utils.prometheus.config.load_kube_config")
    @patch("krkn_ai.utils.prometheus.is_openshift", return_value=False)
    def test_discovery_finds_nothing_raises(
        self, _ocp, _load, mock_net_cls, mock_core_cls
    ):
        """When nothing reachable is found, the actionable config error is raised."""
        mock_net_cls.return_value.list_namespaced_ingress.return_value = (
            SimpleNamespace(items=[])
        )
        mock_core_cls.return_value.list_namespaced_service.return_value = (
            SimpleNamespace(items=[])
        )
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(PrometheusConnectionError) as exc:
                create_prometheus_client("/tmp/test-kubeconfig")
            assert "Prometheus configuration missing" in str(exc.value)
