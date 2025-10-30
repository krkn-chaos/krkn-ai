import os
import json
from krkn_lib.prometheus.krkn_prometheus import KrknPrometheus
from krkn_ai.utils import run_shell
from krkn_ai.utils.logger import get_logger
from krkn_ai.models.custom_errors import PrometheusConnectionError

logger = get_logger(__name__)

def is_openshift(kubeconfig: str) -> bool:
    """
    Check if the cluster is OpenShift.
    """
    _, returncode = run_shell(
        f"kubectl --kubeconfig={kubeconfig} get clusterversions.config.openshift.io",
        do_not_log=True,
    )
    return returncode == 0


def create_prometheus_client(kubeconfig: str) -> KrknPrometheus:
    """
    Create a Prometheus client for the given kubeconfig.

    It first checks if the PROMETHEUS_URL and PROMETHEUS_TOKEN environment variables are set.
    If not, it fetches the Prometheus query endpoint and token from the Kubernetes cluster.

    Args:
        kubeconfig: The path to the Kubernetes configuration file.

    Returns:
        KrknPrometheus: A Prometheus client.
    """
    # Fetch Prometheus query endpoint
    url = os.getenv("PROMETHEUS_URL", "")
    if url == "":
        if is_openshift(kubeconfig):
            prom_spec_json, _ = run_shell(
                f"kubectl --kubeconfig={kubeconfig} -n openshift-monitoring get route -l app.kubernetes.io/name=thanos-query -o json",
                do_not_log=True,
            )
            prom_spec_json = json.loads(prom_spec_json)
            url = prom_spec_json["items"][0]["spec"]["host"]

    if not url.startswith("https://"):
        url = f"https://{url}"

    # Fetch K8s token to access internal service
    token = os.getenv("PROMETHEUS_TOKEN", "")
    if token == "":
        token, _ = run_shell(
            f"oc --kubeconfig={kubeconfig} whoami -t",
            do_not_log=True,
        )

    logger.debug("Prometheus URL: %s", url)

    # Try connecting to Prometheus
    try:
        client = KrknPrometheus(url, token.strip())
        client.process_query("1")
        logger.debug("Successfully connected to Prometheus")
        return client
    except Exception as e:
        # logger.exception("Unable to connect to Prometheus: %s", e)
        raise PrometheusConnectionError("Unable to connect to Prometheus. Please check if Prometheus is running and accessible. Try setting the \"PROMETHEUS_URL\" and \"PROMETHEUS_TOKEN\" environment variables to connect to Prometheus instance.")
