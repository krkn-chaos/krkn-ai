"""
Unit tests for Prometheus utility functions and client creation logic using Kubernetes Python client.
"""

import os
import threading
import time
import pytest
from unittest.mock import Mock, patch
from krkn_ai.utils.prometheus import (
    PrometheusRateLimiter,
    create_prometheus_client,
    is_openshift,
)
from krkn_ai.models.custom_errors import PrometheusConnectionError


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


class TestPrometheusRateLimiter:
    """Tests for PrometheusRateLimiter concurrency and correctness."""

    def test_invalid_qps_raises_value_error(self):
        """Should raise ValueError if max_queries_per_second is zero or negative."""
        with pytest.raises(ValueError, match="must be positive"):
            PrometheusRateLimiter(max_queries_per_second=0)

        with pytest.raises(ValueError, match="must be positive"):
            PrometheusRateLimiter(max_queries_per_second=-1.5)

    def test_no_sleep_on_first_call(self):
        """First call should never sleep - there is no prior query."""
        limiter = PrometheusRateLimiter(max_queries_per_second=1.0)
        with patch("time.sleep") as mock_sleep:
            limiter.wait_if_needed()
            mock_sleep.assert_not_called()

    def test_concurrent_threads_do_not_hold_lock_while_sleeping(self):
        """
        Threads must NOT hold the lock while sleeping.
        All N threads should acquire and release the lock in quick succession,
        then sleep concurrently. Total lock-hold time should be a tiny fraction
        of the total elapsed time.
        """
        limiter = PrometheusRateLimiter(max_queries_per_second=2.0)  # 0.5s interval

        acquire_events = []

        def run():
            start = time.monotonic()
            limiter.wait_if_needed()
            acquire_events.append(time.monotonic() - start)

        threads = [threading.Thread(target=run) for _ in range(5)]
        wall_start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        wall_elapsed = time.monotonic() - wall_start

        # All threads must have completed
        assert len(acquire_events) == 5

        # With 5 threads and 0.5s min_interval, the 5th slot is at t=2.0s.
        # Total elapsed should be close to 2.0s (concurrent sleep), not 5*0.5+lock overhead
        assert wall_elapsed < 4.0, (
            f"Threads appear to be sleeping while holding the lock. "
            f"Elapsed: {wall_elapsed:.2f}s (expected ~2.0s)"
        )

    def test_rate_limiter_spaces_calls(self):
        """Calls should be spaced by at least min_interval."""
        limiter = PrometheusRateLimiter(max_queries_per_second=10.0)
        recorded_sleep = []

        with patch("time.sleep", side_effect=lambda s: recorded_sleep.append(s)):
            limiter.wait_if_needed()  # First call - no sleep
            limiter.wait_if_needed()  # Second call - should sleep ~0.1s

        assert len(recorded_sleep) == 1
        assert recorded_sleep[0] > 0
        assert recorded_sleep[0] <= 0.1 + 0.01  # Allow tiny tolerance
