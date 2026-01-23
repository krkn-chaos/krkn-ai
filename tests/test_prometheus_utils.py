import unittest
from unittest.mock import patch, MagicMock
from krkn_ai.utils.prometheus import create_prometheus_client

class TestPrometheusUtils(unittest.TestCase):
    @patch("krkn_ai.utils.prometheus.is_openshift")
    @patch("krkn_ai.utils.prometheus.run_shell")
    @patch("krkn_ai.utils.prometheus.KrknPrometheus")
    def test_create_prometheus_client_success(self, mock_client, mock_run_shell, mock_is_openshift):
        # Setup mocks
        mock_is_openshift.return_value = True
        mock_run_shell.side_effect = [
            ('{"items": [{"spec": {"host": "prometheus-url"}}]}', 0), # get route
            ('token', 0) # get token
        ]
        
        # Execute
        create_prometheus_client("kubeconfig")
        
        # Verify
        mock_client.assert_called_with("https://prometheus-url", "token")

    @patch("krkn_ai.utils.prometheus.is_openshift")
    @patch("krkn_ai.utils.prometheus.run_shell")
    @patch("krkn_ai.utils.prometheus.KrknPrometheus")
    def test_create_prometheus_client_command_failure(self, mock_client, mock_run_shell, mock_is_openshift):
        # Setup mocks
        mock_is_openshift.return_value = True
        mock_run_shell.side_effect = [
            ('Command failed', 1), # get route failure
            ('token', 0) # get token
        ]
        
        # Execute
        create_prometheus_client("kubeconfig")
        
        # Verify - URL should be empty string (default) causing connection to likely fail or use partial
        # But importantly, it should NOT crash
        mock_client.assert_called()
        args, _ = mock_client.call_args
        self.assertEqual(args[0], "") # URL should remain empty default

    @patch("krkn_ai.utils.prometheus.is_openshift")
    @patch("krkn_ai.utils.prometheus.run_shell")
    @patch("krkn_ai.utils.prometheus.KrknPrometheus")
    def test_create_prometheus_client_invalid_json(self, mock_client, mock_run_shell, mock_is_openshift):
        # Setup mocks
        mock_is_openshift.return_value = True
        mock_run_shell.side_effect = [
            ('Invalid JSON', 0), # get route success but bad output
            ('token', 0) # get token
        ]
        
        # Execute
        create_prometheus_client("kubeconfig")
        
        # Verify - Should not crash
        mock_client.assert_called()
        args, _ = mock_client.call_args
        self.assertEqual(args[0], "")

if __name__ == "__main__":
    unittest.main()
