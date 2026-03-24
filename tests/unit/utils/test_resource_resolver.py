"""
Tests for resolve_pod_name in pvc_utils
"""

from unittest.mock import Mock, patch
from krkn_ai.utils import pvc_utils
from krkn_ai.utils.pvc_utils import resolve_pod_name


class TestResolvePodName:
    """Test resolve_pod_name function"""

    def setup_method(self):
        pvc_utils._kubeconfig_path = None

    def test_returns_stored_name_when_no_kubeconfig(self):
        assert (
            resolve_pod_name("test-ns", "cart-old", "ReplicaSet", "cart-abc")
            == "cart-old"
        )

    def test_returns_stored_name_when_no_owner(self):
        pvc_utils._kubeconfig_path = "/tmp/kubeconfig"
        assert resolve_pod_name("test-ns", "bare-pod") == "bare-pod"

    @patch("krkn_ai.utils.pvc_utils.KrknKubernetes")
    def test_resolves_to_new_pod_name_via_owner_reference(self, mock_krkn_cls):
        pvc_utils._kubeconfig_path = "/tmp/kubeconfig"

        mock_ref = Mock()
        mock_ref.kind = "ReplicaSet"
        mock_ref.name = "cart-abc"

        live_pod = Mock()
        live_pod.metadata.name = "cart-new-xyz"
        live_pod.metadata.owner_references = [mock_ref]

        mock_krkn_cls.return_value.cli.list_namespaced_pod.return_value.items = [
            live_pod
        ]

        result = resolve_pod_name(
            "robot-shop", "cart-old-def", "ReplicaSet", "cart-abc"
        )
        assert result == "cart-new-xyz"

    @patch("krkn_ai.utils.pvc_utils.KrknKubernetes")
    def test_falls_back_when_no_matching_live_pod(self, mock_krkn_cls):
        pvc_utils._kubeconfig_path = "/tmp/kubeconfig"

        mock_ref = Mock()
        mock_ref.kind = "ReplicaSet"
        mock_ref.name = "other-rs"

        unrelated_pod = Mock()
        unrelated_pod.metadata.name = "other-pod"
        unrelated_pod.metadata.owner_references = [mock_ref]

        mock_krkn_cls.return_value.cli.list_namespaced_pod.return_value.items = [
            unrelated_pod
        ]

        result = resolve_pod_name(
            "robot-shop", "cart-old-def", "ReplicaSet", "cart-abc"
        )
        assert result == "cart-old-def"

    @patch("krkn_ai.utils.pvc_utils.KrknKubernetes")
    def test_falls_back_on_api_exception(self, mock_krkn_cls):
        pvc_utils._kubeconfig_path = "/tmp/kubeconfig"

        mock_krkn_cls.return_value.cli.list_namespaced_pod.side_effect = Exception(
            "connection refused"
        )

        result = resolve_pod_name("robot-shop", "cart-old", "ReplicaSet", "cart-abc")
        assert result == "cart-old"

    @patch("krkn_ai.utils.pvc_utils.KrknKubernetes")
    def test_distinguishes_pods_from_different_owners(self, mock_krkn_cls):
        pvc_utils._kubeconfig_path = "/tmp/kubeconfig"

        wrong_ref = Mock()
        wrong_ref.kind = "ReplicaSet"
        wrong_ref.name = "cart-v2-abc"

        wrong_owner_pod = Mock()
        wrong_owner_pod.metadata.name = "cart-v2-new"
        wrong_owner_pod.metadata.owner_references = [wrong_ref]

        correct_ref = Mock()
        correct_ref.kind = "ReplicaSet"
        correct_ref.name = "cart-v1-abc"

        correct_owner_pod = Mock()
        correct_owner_pod.metadata.name = "cart-v1-new"
        correct_owner_pod.metadata.owner_references = [correct_ref]

        mock_krkn_cls.return_value.cli.list_namespaced_pod.return_value.items = [
            wrong_owner_pod,
            correct_owner_pod,
        ]

        result = resolve_pod_name(
            "robot-shop", "cart-v1-old", "ReplicaSet", "cart-v1-abc"
        )
        assert result == "cart-v1-new"
