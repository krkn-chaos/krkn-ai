"""
Kubeconfig validation utilities.

Krkn-AI launches chaos scenarios inside containers (podman/docker). The
kubeconfig is mounted into the container, but other host filesystem paths
are not. If the kubeconfig references credential files by path (e.g.
`certificate-authority: /root/.minikube/ca.crt`), those paths won't
exist inside the container and the kubernetes-client library raises a
generic `ConfigException` deep in the call stack with no actionable
guidance for the user.

This module validates a kubeconfig up-front so the user gets a clear,
actionable error before any container is launched.
"""

from typing import List, Tuple

import yaml

from krkn_ai.models.custom_errors import KubeconfigValidationError

# Kubeconfig credential keys that reference external file paths.
# Their `*-data` counterparts (`certificate-authority-data`, etc.) are
# base64-embedded and work fine inside containers.
_PATH_BASED_CLUSTER_KEYS = ("certificate-authority",)
_PATH_BASED_USER_KEYS = ("client-certificate", "client-key")


def _find_path_based_credentials(config: dict) -> List[Tuple[str, str]]:
    """
    Walk a kubeconfig dict and return ``(location, value)`` tuples for any
    credential entries that reference an external file path instead of an
    embedded base64 blob.

    The locations use a YAML-style notation (e.g.
    ``users[1].user.client-key``) so the caller can include them verbatim
    in an error message.
    """
    issues: List[Tuple[str, str]] = []

    for i, cluster in enumerate(config.get("clusters", []) or []):
        cluster_block = cluster.get("cluster", {}) or {}
        for key in _PATH_BASED_CLUSTER_KEYS:
            if key in cluster_block:
                issues.append((f"clusters[{i}].cluster.{key}", str(cluster_block[key])))

    for i, user in enumerate(config.get("users", []) or []):
        user_block = user.get("user", {}) or {}
        for key in _PATH_BASED_USER_KEYS:
            if key in user_block:
                issues.append((f"users[{i}].user.{key}", str(user_block[key])))

    return issues


def validate_kubeconfig_for_container_use(kubeconfig_path: str) -> None:
    """
    Verify a kubeconfig is self-contained for use inside containerized
    krkn scenarios.

    Raises :class:`KubeconfigValidationError` with an actionable message
    if the kubeconfig file is missing, malformed, or contains path-based
    credential references that won't resolve inside the krkn container.

    The error message includes the exact ``kubectl config view ... --flatten``
    command needed to regenerate a self-contained kubeconfig, so the user
    can fix the problem in one step.
    """
    try:
        with open(kubeconfig_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise KubeconfigValidationError(
            f"Kubeconfig file not found: {kubeconfig_path}"
        ) from e
    except yaml.YAMLError as e:
        raise KubeconfigValidationError(
            f"Kubeconfig at '{kubeconfig_path}' is not valid YAML: {e}"
        ) from e

    if not isinstance(config, dict):
        raise KubeconfigValidationError(
            f"Kubeconfig at '{kubeconfig_path}' is not a valid YAML mapping"
        )

    issues = _find_path_based_credentials(config)
    if not issues:
        return

    formatted = "\n".join(f"  - {loc}: {val}" for loc, val in issues)
    raise KubeconfigValidationError(
        f"Kubeconfig at '{kubeconfig_path}' uses path-based credential "
        f"references that won't be available inside the krkn container:\n"
        f"{formatted}\n\n"
        f"Krkn-AI launches scenarios inside containers (podman/docker) that "
        f"don't have access to these host paths. Re-export your kubeconfig "
        f"with credentials embedded:\n\n"
        f"  kubectl config view "
        f"--context=$(kubectl config current-context) "
        f"--minify --flatten --raw > kubeconfig.yaml\n\n"
        f"See docs/developer_guide.md for the full setup."
    )
