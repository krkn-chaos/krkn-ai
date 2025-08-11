from os import name
import re
import ssl
from typing import List
from krkn_lib.k8s.krkn_kubernetes import KrknKubernetes
from kubernetes.client.models import V1PodSpec
from chaos_ai.utils.logger import get_module_logger
from chaos_ai.models.cluster_components import ClusterComponents, Container, Namespace, Node, Pod

logger = get_module_logger(__name__)

class ClusterManager:
    def __init__(self, kubeconfig: str):
        self.kubeconfig = kubeconfig
        self.krkn_k8s = KrknKubernetes(kubeconfig_path=kubeconfig)
        self.apps_api = self.krkn_k8s.apps_api
        self.api_client = self.krkn_k8s.api_client
        self.core_api = self.krkn_k8s.cli
        self.custom_obj_api = self.krkn_k8s.custom_object_client
        logger.debug("ClusterManager initialized with kubeconfig: %s", kubeconfig)

    def discover_components(self,
        namespace_pattern: str = None,
        pod_label_pattern: str = None,
        node_label_pattern: str = None
    ) -> ClusterComponents:
        namespaces = self.list_namespaces(namespace_pattern)

        for i, namespace in enumerate(namespaces):
            pods = self.list_pods(namespace, pod_label_pattern)
            namespaces[i].pods = pods

        return ClusterComponents(
            namespaces=namespaces,
            nodes=self.list_nodes(node_label_pattern)
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
        pod_labels_patterns = self.__process_pattern(pod_labels_patterns)

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

    def list_nodes(self, node_label_pattern: str = None) -> List[Node]:
        node_label_pattern = self.__process_pattern(node_label_pattern)

        nodes = self.core_api.list_node().items

        node_list = []

        for node in nodes:
            labels = {}
            for pattern in node_label_pattern:
                for label in node.metadata.labels:
                    if re.match(pattern, label):
                        labels[label] = node.metadata.labels[label]
            node_component = Node(
                name=node.metadata.name,
                labels=labels
            )
            try:
                alloc_cpu = self.parse_cpu(node.status.allocatable["cpu"])
                alloc_mem = self.parse_memory(node.status.allocatable["memory"])
                usage_cpu, usage_mem = self.__fetch_node_metrics(node.metadata.name)
                node_component.free_cpu = alloc_cpu - usage_cpu
                node_component.free_mem = alloc_mem - usage_mem
            except Exception as e:
                logger.error("Failed to fetch node metrics for node %s", node.metadata.name)
            node_list.append(node_component)

        logger.debug("Filtered %d nodes", len(node_list))
        return node_list

    def __process_pattern(self, pattern_string: str) -> List[str]:
        # Check whether multiple namespaces are specified
        if ',' in pattern_string:
            patterns = [pattern.strip() for pattern in pattern_string.split(',')]
        else:
            patterns = [pattern_string.strip()]
        
        return patterns

    def __fetch_node_metrics(self, node: str):
        metrics = self.custom_obj_api.list_cluster_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            plural="nodes"
        )

        for item in metrics["items"]:
            name = item["metadata"]["name"]
            if name == node:
                usage_cpu = item["usage"]["cpu"]       # e.g. "250m"
                usage_mem = item["usage"]["memory"]    # e.g. "1024Mi"
                return self.parse_cpu(usage_cpu), self.parse_memory(usage_mem)

    @staticmethod
    def parse_cpu(cpu_str: str):
        """Convert CPU string (e.g. '250m', '4') to cores as float."""
        if cpu_str.endswith("m"):
            return float(cpu_str[:-1]) / 1000
        return float(cpu_str)

    @staticmethod
    def parse_memory(mem_str: str):
        """Convert memory string (e.g. '16254436Ki', '1024Mi', '1Gi') to MiB."""
        units = {"Ki": 1/1024, "Mi": 1, "Gi": 1024}
        for unit, factor in units.items():
            if mem_str.endswith(unit):
                return float(mem_str[:-len(unit)]) * factor
        # If no unit, assume bytes
        return float(mem_str) / (1024**2)
