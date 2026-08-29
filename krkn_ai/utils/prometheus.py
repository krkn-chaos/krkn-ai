import os
from typing import Optional
from kubernetes import client, config
from krkn_lib.prometheus.krkn_prometheus import KrknPrometheus
from krkn_ai.utils.mock import MockType, is_mock_enabled
from krkn_ai.utils.logger import get_logger
from krkn_ai.models.custom_errors import PrometheusConnectionError

logger = get_logger(__name__)

# Namespaces searched when auto-discovering Prometheus on vanilla Kubernetes.
_K8S_MONITORING_NAMESPACES = ("monitoring", "prometheus", "kube-prometheus-stack")
# Substrings that identify a Prometheus/Thanos Ingress or Service by name.
_PROMETHEUS_NAME_HINTS = ("prometheus", "thanos")


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

    # Case 2: Vanilla Kubernetes. Try to auto-discover an externally reachable
    # Prometheus endpoint (Ingress or LoadBalancer Service) before giving up.
    if not is_ocp and not url:
        url = _discover_k8s_prometheus_url(kubeconfig)
        if not url:
            raise PrometheusConnectionError(
                "Prometheus configuration missing for Kubernetes cluster.\n"
                "Automatic discovery found no externally reachable Prometheus "
                "(Ingress or LoadBalancer Service) in the monitoring namespaces.\n"
                "Please set the following environment variables:\n"
                "  export PROMETHEUS_URL=https://<prometheus-host>\n"
                "  export PROMETHEUS_TOKEN=<bearer-token>"
            )

    # Case 3: OpenShift Auto-discovery
    if is_ocp and not url:
        url = _discover_openshift_prometheus_url(kubeconfig)

    if is_ocp and not token:
        token = _discover_openshift_prometheus_token(kubeconfig)

    if not url:
        raise PrometheusConnectionError(
            "Automatic Prometheus discovery failed on OpenShift.\n"
            "Ensure the monitoring routes are accessible or set explicitly:\n"
            "  export PROMETHEUS_URL=<discovered-url>\n"
            "  export PROMETHEUS_TOKEN=$(oc whoami -t)"
        )

    if is_ocp and not token:
        logger.warning(
            "Automatic Prometheus token discovery returned empty on OpenShift.\n"
            "This is expected for exec/certificate-based auth, but if connection fails,\n"
            "please set the token explicitly:\n"
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


def _monitoring_namespaces() -> list:
    """Namespaces to search for a Prometheus endpoint.

    A ``PROMETHEUS_NAMESPACE`` override is searched first when set.
    """
    override = os.getenv("PROMETHEUS_NAMESPACE", "").strip()
    namespaces = list(_K8S_MONITORING_NAMESPACES)
    if override and override not in namespaces:
        namespaces.insert(0, override)
    return namespaces


def _looks_like_prometheus(name: Optional[str]) -> bool:
    """True if a resource name looks like a Prometheus/Thanos endpoint."""
    if not name:
        return False
    lowered = name.lower()
    return any(hint in lowered for hint in _PROMETHEUS_NAME_HINTS)


def _discover_k8s_prometheus_url(kubeconfig: str) -> str:
    """
    Discover an externally reachable Prometheus URL on a vanilla Kubernetes
    cluster, via an Ingress or a LoadBalancer Service in a monitoring namespace.

    A ClusterIP Service is intentionally ignored: it is not reachable from
    outside the cluster (this is exactly why OpenShift discovery targets a Route).

    Args:
        kubeconfig: Path to the Kubernetes configuration file.

    Returns:
        The discovered URL, or an empty string if none is found.
    """
    try:
        config.load_kube_config(config_file=kubeconfig)
    except Exception as error:
        logger.debug("Could not load kubeconfig for Prometheus discovery: %s", error)
        return ""

    url = _discover_prometheus_from_ingress()
    if url:
        logger.debug("Discovered Prometheus via Ingress: %s", url)
        return url

    url = _discover_prometheus_from_loadbalancer()
    if url:
        logger.debug("Discovered Prometheus via LoadBalancer Service: %s", url)
        return url

    return ""


def _ingress_targets_prometheus(ingress) -> bool:
    """True if an Ingress is named like Prometheus or routes to a Prometheus service."""
    name = getattr(getattr(ingress, "metadata", None), "name", None)
    if _looks_like_prometheus(name):
        return True
    spec = getattr(ingress, "spec", None)
    for rule in getattr(spec, "rules", None) or []:
        http = getattr(rule, "http", None)
        for path in getattr(http, "paths", None) or []:
            service = getattr(getattr(path, "backend", None), "service", None)
            if _looks_like_prometheus(getattr(service, "name", None)):
                return True
    return False


def _first_ingress_host(ingress) -> str:
    """First host declared on an Ingress, or an empty string."""
    spec = getattr(ingress, "spec", None)
    for rule in getattr(spec, "rules", None) or []:
        host = getattr(rule, "host", None)
        if host:
            return host.strip()
    return ""


def _discover_prometheus_from_ingress() -> str:
    """Look for a Prometheus Ingress across the monitoring namespaces."""
    try:
        networking = client.NetworkingV1Api()
    except Exception as error:
        logger.debug("Could not create NetworkingV1Api: %s", error)
        return ""

    for namespace in _monitoring_namespaces():
        try:
            ingresses = networking.list_namespaced_ingress(namespace=namespace).items
        except Exception as error:
            logger.debug("Could not list ingresses in %s: %s", namespace, error)
            continue
        for ingress in ingresses:
            if not _ingress_targets_prometheus(ingress):
                continue
            host = _first_ingress_host(ingress)
            if host:
                scheme = "https" if getattr(ingress.spec, "tls", None) else "http"
                return f"{scheme}://{host}"
    return ""


def _loadbalancer_host(service) -> str:
    """External hostname or IP of a LoadBalancer Service, or an empty string."""
    status = getattr(service, "status", None)
    load_balancer = getattr(status, "load_balancer", None)
    for ingress in getattr(load_balancer, "ingress", None) or []:
        host = getattr(ingress, "hostname", None) or getattr(ingress, "ip", None)
        if host:
            return host.strip()
    return ""


def _first_service_port(service) -> Optional[int]:
    """First declared port of a Service, or None."""
    spec = getattr(service, "spec", None)
    for port in getattr(spec, "ports", None) or []:
        value = getattr(port, "port", None)
        if value:
            return value
    return None


def _discover_prometheus_from_loadbalancer() -> str:
    """Look for a Prometheus LoadBalancer Service across the monitoring namespaces."""
    try:
        core = client.CoreV1Api()
    except Exception as error:
        logger.debug("Could not create CoreV1Api: %s", error)
        return ""

    for namespace in _monitoring_namespaces():
        try:
            services = core.list_namespaced_service(namespace=namespace).items
        except Exception as error:
            logger.debug("Could not list services in %s: %s", namespace, error)
            continue
        for service in services:
            spec = getattr(service, "spec", None)
            if getattr(spec, "type", None) != "LoadBalancer":
                continue
            name = getattr(getattr(service, "metadata", None), "name", None)
            if not _looks_like_prometheus(name):
                continue
            host = _loadbalancer_host(service)
            if not host:
                continue
            port = _first_service_port(service)
            return f"http://{host}:{port}" if port else f"http://{host}"
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
        if not is_mock_enabled(MockType.FITNESS):
            client.process_query("1")
        return client
    except Exception as e:
        raise PrometheusConnectionError(
            f"Failed to connect to Prometheus at {url}.\n"
            f"Error details: {str(e)}\n\n"
            "Check network connectivity and ensure the token is valid."
        )
