from os import name
import re
from typing import List
from krkn_lib.k8s.krkn_kubernetes import KrknKubernetes
from chaos_ai.utils.logger import get_module_logger

logger = get_module_logger(__name__)

class ClusterManager:
    def __init__(self, kubeconfig: str):
        self.kubeconfig = kubeconfig
        self.krkn_k8s = KrknKubernetes(kubeconfig_path=kubeconfig)
        self.apps_api = self.krkn_k8s.apps_api
        self.api_client = self.krkn_k8s.api_client
        logger.debug("ClusterManager initialized with kubeconfig: %s", kubeconfig)

    def discover_components(self, namespace_pattern: str = None) -> List[str]:
        namespaces = self.list_namespaces(namespace_pattern)
        

    def list_namespaces(self, namespace_pattern: str = None) -> List[str]:
        logger.debug("Namespace pattern: %s", namespace_pattern)

        # Pre-process namespace pattern
        if namespace_pattern is None or namespace_pattern == '':
            logger.debug("No namespace pattern found.")
            return []

        # Check whether multiple namespaces are specified
        if ',' in namespace_pattern:
            namespace_pattern = [ns.strip() for ns in namespace_pattern.split(',')]
        else:
            namespace_pattern = [namespace_pattern]

        namespaces = self.krkn_k8s.list_namespaces()

        filtered_namespaces = set()

        for ns in namespaces:
            for pattern in namespace_pattern:
                if re.match(pattern, ns):
                    filtered_namespaces.add(ns)

        logger.debug("Filtered namespaces: %d", len(filtered_namespaces))
        return list(filtered_namespaces)


