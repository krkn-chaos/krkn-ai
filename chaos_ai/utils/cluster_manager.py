from os import name
import re
from typing import List
from krkn_lib.k8s.krkn_kubernetes import KrknKubernetes
from kubernetes.client.models import V1PodSpec
from chaos_ai.utils.logger import get_module_logger
from chaos_ai.models.cluster_components import ClusterComponents, Container, Namespace, Pod

logger = get_module_logger(__name__)

class ClusterManager:
    def __init__(self, kubeconfig: str):
        self.kubeconfig = kubeconfig
        self.krkn_k8s = KrknKubernetes(kubeconfig_path=kubeconfig)
        self.apps_api = self.krkn_k8s.apps_api
        self.api_client = self.krkn_k8s.api_client
        self.core_api = self.krkn_k8s.cli
        logger.debug("ClusterManager initialized with kubeconfig: %s", kubeconfig)

    def discover_components(self, namespace_pattern: str = None, pod_label_pattern: str = None) -> ClusterComponents:
        namespaces = self.list_namespaces(namespace_pattern)

        pod_labels_patterns = self.__process_pattern(pod_label_pattern)

        for i, namespace in enumerate(namespaces):
            pods = self.list_pods(namespace, pod_labels_patterns)
            namespaces[i].pods = pods

        return ClusterComponents(
            namespaces=namespaces
        )


    def list_namespaces(self, namespace_pattern: str = None) -> List[Namespace]:
        logger.debug("Namespace pattern: %s", namespace_pattern)

        namespace_patterns = self.__process_pattern(namespace_pattern)

        namespaces = self.krkn_k8s.list_namespaces()

        filtered_namespaces = set()

        for ns in namespaces:
            for pattern in namespace_patterns:
                if re.match(pattern, ns):
                    filtered_namespaces.add(ns)

        logger.debug("Filtered namespaces: %d", len(filtered_namespaces))
        return [Namespace(name=ns) for ns in filtered_namespaces]

    def list_pods(self, namespace: Namespace, pod_labels_patterns: List[str]) -> List[str]:
        pods = self.core_api.list_namespaced_pod(namespace=namespace.name).items
        pod_list = []

        for pod in pods:
            pod_component = Pod(
                name=pod.metadata.name,
                labels=pod.metadata.labels,
            )
            # Filter label keys by patterns
            labels = {}
            for pattern in pod_labels_patterns:
                for label in pod.metadata.labels:
                    if re.match(pattern, label):
                        labels[label] = pod.metadata.labels[label]
            pod_component.labels = labels
            pod_component.containers = self.list_containers(pod.spec)
            pod_list.append(pod_component)

        logger.debug("Filtered %d pods in namespace %s", len(pod_list), namespace.name)
        return pod_list

    def list_containers(self, pod_spec: V1PodSpec) -> List[Container]:
        containers = []
        for container in pod_spec.containers:
            containers.append(
                Container(
                    name=container.name,
                )
            )
        return containers

    def __process_pattern(self, pattern_string: str) -> List[str]:
        # Check whether multiple namespaces are specified
        if ',' in pattern_string:
            patterns = [pattern.strip() for pattern in pattern_string.split(',')]
        else:
            patterns = [pattern_string.strip()]
        
        return patterns
