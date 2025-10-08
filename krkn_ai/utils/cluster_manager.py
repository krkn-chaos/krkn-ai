from os import name
import re
import ssl
from typing import List
from krkn_lib.k8s.krkn_kubernetes import KrknKubernetes
from kubernetes.client.models import V1PodSpec
from krkn_ai.utils.logger import get_module_logger
from krkn_ai.models.cluster_components import ClusterComponents, Container, Namespace, Node, Pod

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
        node_label_pattern = list(set(self.__process_pattern(node_label_pattern) + ["kubernetes.io/hostname"]))

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
                node_component.free_cpu = -1 # -1 means not available
                node_component.free_mem = -1 # -1 means not available
                logger.error("Failed to fetch node metrics for node %s: %s", node.metadata.name, e)
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
        """
        Parse Kubernetes cpu usage string into millicores (float).
        Examples:
        '363874038n' -> nanocores -> 363.874038 mCPU
        '500u'       -> microcores -> 0.5 mCPU
        '250m'       -> 250 mCPU
        '1' or '0.5' -> cores -> 1000 or 500 mCPU
        Returns float (millicores).
        """
        if cpu_str is None:
            return 0.0
        s = str(cpu_str).strip()
        if s.endswith('n'):        # nanocores
            n = int(s[:-1])
            return n / 1_000_000.0
        if s.endswith('u'):        # microcores
            u = int(s[:-1])
            return u / 1000.0
        if s.endswith('m'):        # millicores
            return float(s[:-1])
        # plain cores: 1, 0.5, 1.25, etc
        try:
            cores = float(s)
            return cores * 1000.0
        except ValueError:
            raise ValueError(f"Unrecognized CPU format: {cpu_str}")

    @staticmethod
    def parse_memory(mem_str: str):
        """
        Parse Kubernetes memory strings into integer bytes.
        Handles binary (Ki,Mi,Gi...) and SI (K,M,G...) and plain numbers (bytes).
        Examples:
        '4745676Ki' -> 4745676 * 1024 bytes
        '128Mi'     -> 134217728
        '512M'      -> 512_000_000
        '1024'      -> 1024
        """
        _mem_power2 = {'Ki':1024, 'Mi':1024**2, 'Gi':1024**3, 'Ti':1024**4, 'Pi':1024**5, 'Ei':1024**6}
        _mem_power10 = {'K':1000, 'M':1000**2, 'G':1000**3, 'T':1000**4, 'P':1000**5, 'E':1000**6}

        if mem_str is None:
            return 0
        s = str(mem_str).strip()
        if re.fullmatch(r'^\d+(\.\d+)?$', s):
            return int(float(s))
        m = re.fullmatch(r'^([0-9.]+)\s*([a-zA-Z]+)$', s)
        if not m:
            raise ValueError(f"Unable to parse memory string: {s}")
        val = float(m.group(1))
        unit = m.group(2)
        # binary units
        if unit in _mem_power2:
            return int(val * _mem_power2[unit])
        # SI units
        if unit in _mem_power10:
            return int(val * _mem_power10[unit])
        # case-insensitive fallback
        u_uc = unit.capitalize()
        if u_uc in _mem_power2:
            return int(val * _mem_power2[u_uc])
        raise ValueError(f"Unknown memory unit: {unit}")
