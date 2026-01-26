import os
from kubernetes import client, config
from krkn_lib.prometheus.krkn_prometheus import KrknPrometheus
from krkn_ai.utils.fs import env_is_truthy
from krkn_ai.utils.logger import get_logger
from krkn_ai.models.custom_errors import PrometheusConnectionError

logger = get_logger(__name__)


def is_openshift(kubeconfig: str) -> bool:
    """
    Checks if the targeted cluster is an OpenShift cluster.

    Attempts to query OpenShift cluster versions via the Kubernetes Python client.

    Args:
        kubeconfig: Path to the Kubernetes configuration file.

    Returns:
        True if the cluster is OpenShift, False otherwise.
    """
    try:
        config.load_kube_config(config_file=kubeconfig)
        api = client.CustomObjectsApi()
        api.list_cluster_custom_object(
            group="config.openshift.io",
            version="v1",
            plural="clusterversions",
        )
        return True
    except Exception:
        return False


def create_prometheus_client(kubeconfig: str) -> KrknPrometheus:
    """
    Creates a Prometheus client with intelligent discovery and fallback logic.

    Discovery Priority:
    1. Explicit environment variables: `PROMETHEUS_URL` and `PROMETHEUS_TOKEN`.
    2. OpenShift Auto-discovery: If the cluster is OpenShift, attempts to discover
       the URL from routes and the token from the kubeconfig context.
    3. Error: Raises `PrometheusConnectionError` with actionable instructions.

    Args:
        kubeconfig: Path to the Kubernetes configuration file.

    Returns:
        A configured KrknPrometheus client instance.

    Raises:
        PrometheusConnectionError: If Prometheus cannot be discovered or accessed.
    """
    url = os.getenv("PROMETHEUS_URL", "").strip()
    token = os.getenv("PROMETHEUS_TOKEN", "").strip()

    # Case 1: Both environment variables provided
    if url and token:
        return _validate_and_create_client(url, token)

    is_ocp = is_openshift(kubeconfig)

    # Case 2: For non-OpenShift clusters, both variables are required.
    if not is_ocp and (not url or not token):
        raise PrometheusConnectionError(
            "Prometheus configuration missing for Kubernetes cluster.\n"
            "Please set the following environment variables:\n"
            "  export PROMETHEUS_URL=https://<prometheus-host>\n"
            "  export PROMETHEUS_TOKEN=<bearer-token>\n\n"
            "For generic Kubernetes clusters, explicit configuration is required."
        )

    # Case 3: OpenShift Auto-discovery
    if is_ocp and not url:
        url = _discover_openshift_prometheus_url(kubeconfig)

    if is_ocp and not token:
        token = _discover_openshift_prometheus_token(kubeconfig)

    if not url or not token:
        raise PrometheusConnectionError(
            "Automatic Prometheus discovery failed on OpenShift.\n"
            "Ensure the monitoring routes are accessible or set explicitly:\n"
            "  export PROMETHEUS_URL=<discovered-url>\n"
            "  export PROMETHEUS_TOKEN=$(oc whoami -t)"
        )

    return _validate_and_create_client(url, token)


def _discover_openshift_prometheus_url(kubeconfig: str) -> str:
    """
    Attempts to discover the Prometheus (Thanos Query) URL from OpenShift routes.

    Args:
        kubeconfig: Path to the Kubernetes configuration file.

    Returns:
        The discovered host URL or an empty string if discovery fails.
    """
    try:
        config.load_kube_config(config_file=kubeconfig)
        api = client.CustomObjectsApi()
        routes = api.list_namespaced_custom_object(
            group="route.openshift.io",
            version="v1",
            namespace="openshift-monitoring",
            plural="routes",
            label_selector="app.kubernetes.io/name=thanos-query",
        )
        items = routes.get("items", [])
        if not items:
            logger.debug("No Prometheus Thanos Query routes found")
            return ""

        # Safely extract host from the first route
        host = items[0].get("spec", {}).get("host", "").strip()
        return host
    except Exception as e:
        logger.debug(f"Unexpected error during URL discovery: {e}")
        return ""


def _discover_openshift_prometheus_token(kubeconfig: str) -> str:
    """
    Extracts authentication token directly from loaded kubeconfig context.

    Args:
        kubeconfig: Path to the Kubernetes configuration file.

    Returns:
        The authentication token or an empty string if discovery fails.
    """
    try:
        config.load_kube_config(config_file=kubeconfig)
        api_client = config.new_client_from_config(config_file=kubeconfig)
        token = api_client.configuration.api_key.get("authorization")
        if token:
            return token.replace("Bearer ", "")
        return ""
    except Exception as e:
        logger.debug(f"Unexpected error during token discovery: {e}")
        return ""


def _validate_and_create_client(url: str, token: str) -> KrknPrometheus:
    """
    Validates connection parameters and initializes the Prometheus client.

    Args:
        url: The Prometheus API endpoint URL.
        token: Authentication token.

    Returns:
        An initialized KrknPrometheus client.

    Raises:
        PrometheusConnectionError: If the connection test fails.
    """
    # Ensure URL has a protocol scheme
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    logger.debug("Initializing Prometheus client: %s", url)

    try:
        client = KrknPrometheus(url.strip(), token.strip())
        # Connection test: run a dummy query unless in mock mode
        if not env_is_truthy("MOCK_FITNESS"):
            client.process_query("1")
        return client
    except Exception as e:
        raise PrometheusConnectionError(
            f"Failed to connect to Prometheus at {url}.\n"
            f"Error details: {str(e)}\n\n"
            "Check network connectivity and ensure the token is valid."
        )
