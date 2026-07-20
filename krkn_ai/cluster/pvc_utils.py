"""
Kubernetes resource utilities: PVC usage lookups and pod name resolution.
"""

from typing import Optional, Dict, Tuple
import time
from krkn_lib.k8s.krkn_kubernetes import KrknKubernetes
from krkn_lib.telemetry.k8s import KrknTelemetryKubernetes
from krkn_ai.utils.logger import get_logger
from krkn_lib.utils import SafeLogger

logger = get_logger(__name__)

# Global kubeconfig path, set by initialize_kubeconfig()
_kubeconfig_path: Optional[str] = None

# Cache expires after 5 seconds to balance real-time accuracy and performance
_pvc_usage_cache: Dict[Tuple[str, str], Tuple[float, float]] = {}
_cache_ttl = 5.0  # Cache TTL in seconds
_logged_pvcs: set = set()


def initialize_kubeconfig(kubeconfig_path: str):
    """
    Initialize the global kubeconfig path.
    Called once at startup by ScenarioFactory.

    Args:
        kubeconfig_path: Path to kubeconfig file
    """
    global _kubeconfig_path
    _kubeconfig_path = kubeconfig_path


def resolve_pod_name(
    namespace: str,
    pod_name: str,
    owner_kind: Optional[str] = None,
    owner_name: Optional[str] = None,
    kubeconfig: Optional[str] = None,
) -> str:
    """
    Resolve a potentially stale pod name to the current running pod name
    using the pod's owner reference.

    Pods managed by controllers (Deployments, StatefulSets, etc.) get new
    names when recreated after chaos scenarios. This uses the owner reference
    stored during discovery to find the current running pod.

    Falls back to the stored pod name if no kubeconfig is available (unit
    tests), the pod has no owner reference (bare pod), or resolution fails.

    Args:
        namespace: Namespace where the pod lives
        pod_name: Pod name from cluster_components config
        owner_kind: Controller kind (e.g. "ReplicaSet", "StatefulSet")
        owner_name: Controller name (e.g. "cart-655b74fb49")
        kubeconfig: Optional explicit kubeconfig path

    Returns:
        Current pod name, or the stored name as fallback
    """
    kubeconfig_path = kubeconfig or _kubeconfig_path
    if not kubeconfig_path:
        return pod_name

    if not owner_kind or not owner_name:
        return pod_name

    try:
        krkn_k8s = KrknKubernetes(kubeconfig_path=kubeconfig_path)
        live_pods = krkn_k8s.cli.list_namespaced_pod(
            namespace=namespace,
            field_selector="status.phase=Running",
        ).items

        for live_pod in live_pods:
            if not live_pod.metadata.owner_references:
                continue
            ref = live_pod.metadata.owner_references[0]
            if ref.kind == owner_kind and ref.name == owner_name:
                logger.debug(
                    "Resolved pod %s -> %s (owner: %s/%s)",
                    pod_name,
                    live_pod.metadata.name,
                    owner_kind,
                    owner_name,
                )
                return live_pod.metadata.name

        logger.debug(
            "No running pod found for owner %s/%s in %s, using stored name %s",
            owner_kind,
            owner_name,
            namespace,
            pod_name,
        )
        return pod_name
    except Exception as e:
        logger.debug(
            "Failed to resolve pod name for %s in %s: %s",
            pod_name,
            namespace,
            str(e),
        )
        return pod_name


def get_pvc_usage_percentage(
    pvc_name: str, namespace: str, kubeconfig: Optional[str] = None
) -> Optional[float]:
    """
    Get current usage percentage of a PVC in real-time.
    Uses a short-term cache (5 seconds) to avoid excessive API calls when creating multiple scenarios.

    Args:
        pvc_name: Name of the PVC
        namespace: Namespace where the PVC exists
        kubeconfig: Optional path to kubeconfig file. If not provided, uses the globally initialized kubeconfig.

    Returns:
        Usage percentage (0-100) or None if unable to get
    """
    # Use provided kubeconfig or fall back to global one
    kubeconfig_path = kubeconfig or _kubeconfig_path
    if not kubeconfig_path:
        logger.debug("No kubeconfig provided and global kubeconfig not initialized")
        return None
    # Check cache first
    cache_key = (namespace, pvc_name)
    current_time = time.time()

    if cache_key in _pvc_usage_cache:
        cached_usage, cached_timestamp = _pvc_usage_cache[cache_key]
        if current_time - cached_timestamp < _cache_ttl:
            # Return cached value without logging to reduce log noise
            return cached_usage
        else:
            # Cache expired, remove it and allow logging again
            del _pvc_usage_cache[cache_key]
            _logged_pvcs.discard(cache_key)

    try:
        safe_logger = SafeLogger()
        lib_kubernetes = KrknKubernetes(kubeconfig_path=kubeconfig_path)
        lib_telemetry = KrknTelemetryKubernetes(
            safe_logger=safe_logger, lib_kubernetes=lib_kubernetes
        )

        # Find a pod that uses this PVC (we know pvc_name, need to find pod_name)
        krkn_k8s = KrknKubernetes(kubeconfig_path=kubeconfig_path)
        pods = krkn_k8s.cli.list_namespaced_pod(
            namespace=namespace, field_selector="status.phase=Running"
        ).items

        pod_name = None
        volume_name = None
        for pod in pods:
            if pod.spec.volumes:
                for volume in pod.spec.volumes:
                    if (
                        volume.persistent_volume_claim
                        and volume.persistent_volume_claim.claim_name == pvc_name
                    ):
                        pod_name = pod.metadata.name
                        volume_name = volume.name
                        break
                if pod_name:
                    break

        if not pod_name or not volume_name:
            logger.debug(
                "No running pod found using PVC %s in namespace %s", pvc_name, namespace
            )
            return None

        # Get pod info (following reference code pattern exactly)
        pod = lib_telemetry.get_lib_kubernetes().get_pod_info(
            name=pod_name, namespace=namespace
        )
        if pod is None:
            logger.debug("Pod %s doesn't exist in namespace %s", pod_name, namespace)
            return None

        # Get container name and mount path (following reference code pattern exactly)
        mount_path = None
        container_name = None
        for container in pod.containers:
            for vol in container.volumeMounts:
                if vol.name == volume_name:
                    mount_path = vol.mountPath
                    container_name = container.name
                    break

        if not mount_path or not container_name:
            logger.debug("No mount path found for PVC %s in pod %s", pvc_name, pod_name)
            return None

        # Get PVC capacity and used bytes (following reference code pattern exactly)
        command = "df %s -B 1024 | sed 1d" % (str(mount_path))
        command_output = (
            lib_telemetry.get_lib_kubernetes().exec_cmd_in_pod(
                [command], pod_name, namespace, container_name
            )
        ).split()

        if len(command_output) < 4:
            logger.debug(
                "Unexpected df output format for PVC %s: %s", pvc_name, command_output
            )
            return None

        pvc_used_kb = int(command_output[2])
        pvc_capacity_kb = pvc_used_kb + int(command_output[3])

        if pvc_capacity_kb > 0:
            current_usage = (pvc_used_kb / pvc_capacity_kb) * 100
            # Cache the result
            _pvc_usage_cache[cache_key] = (current_usage, current_time)
            # Only log once per PVC to reduce log noise
            if cache_key not in _logged_pvcs:
                logger.info(
                    "Found PVC %s usage: %.2f%% (used: %d KB, capacity: %d KB)",
                    pvc_name,
                    current_usage,
                    pvc_used_kb,
                    pvc_capacity_kb,
                )
                _logged_pvcs.add(cache_key)
            return current_usage
        else:
            logger.debug("PVC %s capacity is 0, cannot calculate usage", pvc_name)
            return None
    except Exception as e:
        logger.debug(
            "Failed to get usage for PVC %s in namespace %s: %s",
            pvc_name,
            namespace,
            str(e),
        )
        return None
