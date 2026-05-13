"""
Unit tests for template generator with Prometheus integration.
"""

from krkn_ai.templates.generator import create_krkn_ai_template


class TestCreateKrknAiTemplate:
    """Tests for create_krkn_ai_template with Prometheus params."""

    def test_template_with_suggested_queries(self):
        """Should render suggested queries in fitness_function block."""
        result = create_krkn_ai_template(
            kubeconfig_file_path="/tmp/kubeconfig",
            cluster_component_data={"namespaces": []},
            prometheus_url="https://prometheus.example.com",
            suggested_queries=[
                'sum(kube_pod_container_status_restarts_total{namespace=~"ns1"})',
                'sum(rate(container_cpu_usage_seconds_total{namespace=~"ns1"}[5m]))',
            ],
            discovered_namespaces=["ns1"],
        )

        assert (
            "Prometheus endpoint auto-discovered: https://prometheus.example.com"
            in result
        )
        assert "PROMETHEUS_URL=https://prometheus.example.com" in result
        assert (
            "Fitness function queries suggested from discovered Prometheus metrics"
            in result
        )
        assert (
            "query: 'sum(kube_pod_container_status_restarts_total{namespace=~\"ns1\"})'"
            in result
        )
        assert "Scoped to namespaces: ns1" in result
        # Second query should be commented
        assert (
            "#   query: 'sum(rate(container_cpu_usage_seconds_total{namespace=~\"ns1\"}[5m]))'"
            in result
        )

    def test_template_without_suggested_queries(self):
        """Should render default fitness_function when no suggestions available."""
        result = create_krkn_ai_template(
            kubeconfig_file_path="/tmp/kubeconfig",
            cluster_component_data={"namespaces": []},
        )

        assert "Prometheus endpoint auto-discovered" not in result
        assert "query: 'sum(kube_pod_container_status_restarts_total)'" in result

    def test_template_without_prometheus_url(self):
        """Should not render Prometheus comment when URL is empty."""
        result = create_krkn_ai_template(
            kubeconfig_file_path="/tmp/kubeconfig",
            cluster_component_data={"namespaces": []},
            prometheus_url="",
            suggested_queries=[],
        )

        assert "Prometheus endpoint auto-discovered" not in result

    def test_template_with_multiple_namespaces(self):
        """Should list all discovered namespaces in the comment."""
        result = create_krkn_ai_template(
            kubeconfig_file_path="/tmp/kubeconfig",
            cluster_component_data={"namespaces": []},
            prometheus_url="https://prom.local",
            suggested_queries=[
                'sum(kube_pod_container_status_restarts_total{namespace=~"ns1|ns2|ns3"})',
            ],
            discovered_namespaces=["ns1", "ns2", "ns3"],
        )

        assert "Scoped to namespaces: ns1, ns2, ns3" in result
