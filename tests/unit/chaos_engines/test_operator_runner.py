import os
from unittest.mock import patch

from kubernetes.config.config_exception import ConfigException

from krkn_ai.chaos_engines.operator_runner import OperatorExecutor


class TestOperatorExecutorAuthentication:
    def test_falls_back_to_cli_kubeconfig_outside_cluster(self):
        config = type("Config", (), {"kubeconfig_file_path": "/tmp/test-kubeconfig"})()
        operator_env = {
            "KRKNAI_NAMESPACE": "krkn-operator",
            "KRKNAI_RUN_NAME": "manual-run",
            "KRKNAI_RUN_UID": "run-uid",
            "KRKNAI_TARGET_REQUEST_ID": "self",
            "KRKNAI_PROVIDER": "krkn-operator",
            "KRKNAI_CLUSTER": "self",
        }

        with (
            patch.dict(os.environ, operator_env, clear=False),
            patch(
                "krkn_ai.chaos_engines.operator_runner.kube_config.load_incluster_config",
                side_effect=ConfigException("not running in a cluster"),
            ) as load_incluster,
            patch(
                "krkn_ai.chaos_engines.operator_runner.kube_config.load_kube_config"
            ) as load_kubeconfig,
        ):
            OperatorExecutor(config)

        load_incluster.assert_called_once_with()
        load_kubeconfig.assert_called_once_with(config_file="/tmp/test-kubeconfig")
