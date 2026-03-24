import re
from typing import List, Optional, Union
from krkn_lib.k8s.krkn_kubernetes import KrknKubernetes
from kubernetes.client.models import V1PodSpec
from krkn_ai.utils import run_shell
from krkn_ai.utils.logger import get_logger
from krkn_ai.models.custom_errors import ShellCommandTimeoutError
from krkn_ai.utils.pattern_matcher import PatternMatcher
from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Container,
    Namespace,
    Node,
    OwnerReference,
    Pod,
    PVC,
    Service,
    ServicePort,
)
from krkn_ai.models.cluster_components import VMI

logger = get_logger(__name__)


class ClusterManager:
    def __init__(self, kubeconfig: str):
        self.kubeconfig = kubeconfig
        self.krkn_k8s = KrknKubernetes(kubeconfig_path=kubeconfig)
        self.apps_api = self.krkn_k8s.apps_api
        self.api_client = self.krkn_k8s.api_client
        self.core_api = self.krkn_k8s.cli
        self.custom_obj_api = self.krkn_k8s.custom_object_client
        logger.debug("ClusterManager initialized with kubeconfig: %s", kubeconfig)

    def discover_components(
        self,
        namespace_pattern: Optional[str] = None,
        pod_label_pattern: Optional[str] = None,
        node_label_pattern: Optional[str] = None,
        skip_pod_name: Optional[str] = None,
    ) -> ClusterComponents:
        """
        Discover cluster components with optional filtering.

        Args:
            namespace_pattern: Pattern for namespace names.
                - None or '': Match no namespaces (explicit selection required)
                - '*': Match all namespaces
                - 'default,kube.*': Comma-separated patterns
                - '!kube-system': Exclude pattern
                Examples: 'default', 'default,kube.*', 'prod-.*', '*,!kube-system'
            pod_label_pattern: Pattern for pod label keys to include (optional)
            node_label_pattern: Pattern for node label keys to include (optional)
            skip_pod_name: Pattern for pod names to skip (optional)

        Returns:
            ClusterComponents with discovered namespaces, pods, services, etc.
        """
        namespaces = self.list_namespaces(namespace_pattern)

        for i, namespace in enumerate(namespaces):
            pods = self.list_pods(namespace, pod_label_pattern, skip_pod_name)
            namespaces[i].pods = pods
            namespaces[i].services = self.list_services(namespace)
            namespaces[i].pvcs = self.list_pvcs(namespace)

            vmis = self.list_vmis(namespace)
            namespaces[i].vmis = vmis

        return ClusterComponents(
            namespaces=namespaces, nodes=self.list_nodes(node_label_pattern)
        )

    def list_namespaces(
        self, namespace_pattern: Optional[str] = None
    ) -> List[Namespace]:
        """
        List namespaces filtered by optional pattern.

        Args:
            namespace_pattern: Pattern to match namespace names.
                - None or '': Match no namespaces (explicit selection required)
                - '*': Match all namespaces
                - 'pattern1,pattern2': Match multiple comma-separated patterns
                - 'kube-.*': Regex pattern for namespaces starting with 'kube-'
                - '!kube-system': Match all EXCEPT kube-system
                - 'openshift-.*,!openshift-operators': Include/exclude combination

        Returns:
            List of matching Namespace objects
        """
        logger.debug("Namespace pattern: %s", namespace_pattern)

        # Use PatternMatcher with default_match_all=False (explicit selection required)
        matcher = PatternMatcher.from_string(namespace_pattern, default_match_all=False)

        if matcher.is_empty():
            logger.debug("No namespace pattern provided, returning empty list ")
            return []

        namespaces = self.krkn_k8s.list_namespaces()

        if not namespaces:
            logger.debug("No namespaces found in cluster")
            return []

        filtered_namespaces = matcher.filter(namespaces)

        logger.debug(
            "Filtered namespaces: %d/%d (pattern: %s)",
            len(filtered_namespaces),
            len(namespaces),
            namespace_pattern,
        )

        if not filtered_namespaces and namespaces:
            logger.warning(
                "No namespaces matched pattern '%s'. Available namespaces: %s",
                namespace_pattern,
                ", ".join(sorted(namespaces[:10])),
            )

        return [Namespace(name=ns) for ns in sorted(filtered_namespaces)]

    def list_pods(
        self,
        namespace: Namespace,
        pod_labels_patterns: Optional[Union[str, List[str]]] = None,
        skip_pod_name_patterns: Optional[Union[str, List[str]]] = None,
    ) -> List[Pod]:
        """
        List pods in a namespace with optional label filtering and skip patterns.

        Args:
            namespace: The namespace to list pods from
            pod_labels_patterns: Pattern for pod label keys to include.
                - None or '': Include all labels (default_match_all=True)
                - '*': Include all labels
                - 'app,env': Include specific label keys
                - 'app.*': Regex pattern for label keys
            skip_pod_name_patterns: Pattern for pod names to skip.
                - None or '': Skip nothing
                - 'test-.*': Skip pods matching pattern
                - 'debug-pod,test-pod': Skip specific pods

        Returns:
            List of Pod objects
        """
        # For label patterns, default to match all if not specified
        label_matcher = PatternMatcher.from_string(
            pod_labels_patterns, default_match_all=True
        )

        # For skip patterns, default to match nothing (skip nothing)
        skip_matcher = PatternMatcher.from_string(
            skip_pod_name_patterns, default_match_all=False
        )

        pods = self.core_api.list_namespaced_pod(
            namespace=namespace.name, field_selector="status.phase=Running"
        ).items
        pod_list = []

        for pod in pods:
            # Skip if podname matches skip pattern
            if skip_matcher.matches(pod.metadata.name):
                logger.debug(
                    "Skipping pod %s in namespace %s", pod.metadata.name, namespace.name
                )
                continue

            owner = None
            if pod.metadata.owner_references:
                ref = pod.metadata.owner_references[0]
                owner = OwnerReference(name=ref.name, kind=ref.kind)

            pod_component = Pod(
                name=pod.metadata.name,
                owner=owner,
            )
            # Filter label keys by patterns
            labels = {}
            if pod.metadata.labels is not None:
                for label_key, label_value in pod.metadata.labels.items():
                    if label_matcher.matches(label_key):
                        labels[label_key] = label_value
            pod_component.labels = labels
            pod_component.containers = self.list_containers(pod.spec)
            pod_list.append(pod_component)

        logger.debug("Filtered %d pods in namespace %s", len(pod_list), namespace.name)
        return pod_list

    def list_services(self, namespace: Namespace) -> List[Service]:
        services = self.core_api.list_namespaced_service(namespace=namespace.name).items
        service_list = []

        for svc in services:
            ports = []
            if svc.spec.ports is not None:
                for port in svc.spec.ports:
                    if port.port is None:
                        continue
                    ports.append(
                        ServicePort(
                            port=port.port,
                            target_port=port.target_port,
                            protocol=port.protocol or "TCP",
                        )
                    )

            service_list.append(
                Service(
                    name=svc.metadata.name,
                    labels=svc.metadata.labels or {},
                    ports=ports,
                )
            )

        logger.debug(
            "Discovered %d services in namespace %s", len(service_list), namespace.name
        )
        return service_list

    def list_pvcs(self, namespace: Namespace) -> List[PVC]:
        """List all PVCs in the namespace"""
        try:
            pvcs = self.core_api.list_namespaced_persistent_volume_claim(
                namespace=namespace.name
            ).items
            pvc_list = []

            for pvc in pvcs:
                pvc_list.append(
                    PVC(
                        name=pvc.metadata.name,
                        labels=pvc.metadata.labels or {},
                    )
                )

            logger.debug(
                "Discovered %d PVCs in namespace %s", len(pvc_list), namespace.name
            )
            return pvc_list
        except Exception as e:
            logger.warning(
                "Failed to list PVCs in namespace %s: %s", namespace.name, str(e)
            )
            return []

    def list_containers(self, pod_spec: V1PodSpec) -> List[Container]:
        containers = []
        for container in pod_spec.containers:
            containers.append(
                Container(
                    name=container.name,
                )
            )
        return containers

    def list_vmis(self, namespace: Namespace) -> List[VMI]:
        try:
            vmis_response = self.custom_obj_api.list_namespaced_custom_object(
                "kubevirt.io", "v1", namespace.name, "virtualmachineinstances"
            )
            vmis = vmis_response.get("items", [])
            vmi_list = []
            if vmis:
                logger.debug(
                    "Found %d vmis in namespace %s",
                    len(vmis),
                    vmis[0]["metadata"]["name"],
                )
            else:
                logger.debug("No VMIs found in namespace %s", namespace.name)
            for vmi in vmis:
                vmi_component = VMI(name=vmi["metadata"]["name"])
                vmi_list.append(vmi_component)

            logger.debug(
                "Filtered %d vmis in namespace %s", len(vmi_list), namespace.name
            )
            return vmi_list
        except Exception:
            logger.warning("Unable to find VMIs in namespace %s", namespace.name)
            return []

    def list_nodes(
        self, node_label_pattern: Optional[Union[str, List[str]]] = None
    ) -> List[Node]:
        """
        List nodes with optional label filtering.

        Args:
            node_label_pattern: Pattern for node label keys to include.
                - None or '': Include all labels (default_match_all=True)
                - '*': Include all labels
                - 'kubernetes.io/hostname': Include specific labels
                - 'node-role.*': Regex pattern for label keys

        Returns:
            List of Node objects
        """
        # For label patterns, default to match all if not specified
        label_matcher = PatternMatcher.from_string(
            node_label_pattern, default_match_all=True
        )

        # If specific patterns provided, ensure hostname is always included
        if not label_matcher.match_all and label_matcher.include_patterns:
            # Check if hostname pattern is already included
            hostname_key = "kubernetes.io/hostname"
            if not label_matcher.matches(hostname_key):
                # Add hostname pattern to the matcher
                label_matcher.include_patterns.append(
                    PatternMatcher._compile_pattern(hostname_key)
                )

        nodes = self.core_api.list_node().items

        node_list = []

        for node in nodes:
            # Check whether node is unschedulable
            if node.spec.unschedulable:
                logger.debug("Node %s is unschedulable, skipping", node.metadata.name)
                continue
            # Check whether node is not Ready
            is_ready = False
            for condition in node.status.conditions:
                if condition.type == "Ready" and condition.status == "True":
                    is_ready = True
                    break
            if not is_ready:
                logger.debug("Node %s is not Ready, skipping", node.metadata.name)
                continue

            labels = {}
            if node.metadata.labels is not None:
                for label_key, label_value in node.metadata.labels.items():
                    if label_matcher.matches(label_key):
                        labels[label_key] = label_value
            # Get node taints and format as strings: "key:effect" or "key=value:effect"
            taints = []
            if node.spec.taints is not None:
                for taint in node.spec.taints:
                    if taint.value is not None:
                        taint_str = f"{taint.key}={taint.value}:{taint.effect}"
                    else:
                        taint_str = f"{taint.key}:{taint.effect}"
                    taints.append(taint_str)

            node_component = Node(name=node.metadata.name, labels=labels, taints=taints)

            try:
                node_component.interfaces = self.list_node_interfaces(
                    node.metadata.name
                )
            except Exception as e:
                logger.error(
                    "Failed to list node interfaces for node %s: %s",
                    node.metadata.name,
                    e,
                )

            try:
                alloc_cpu = self.parse_cpu(node.status.allocatable["cpu"])
                alloc_mem = self.parse_memory(node.status.allocatable["memory"])
                usage_cpu, usage_mem = self.__fetch_node_metrics(node.metadata.name)
                node_component.free_cpu = alloc_cpu - usage_cpu
                node_component.free_mem = alloc_mem - usage_mem
            except Exception as e:
                node_component.free_cpu = -1  # -1 means not available
                node_component.free_mem = -1  # -1 means not available
                logger.error(
                    "Failed to fetch node metrics for node %s: %s",
                    node.metadata.name,
                    e,
                )
            node_list.append(node_component)

        logger.debug("Filtered %d nodes", len(node_list))
        return node_list

    def list_node_interfaces(self, node: str) -> List[str]:
        logger.debug("Listing node interfaces for node %s", node)
        try:
            log, code = run_shell(
                f"oc debug -q node/{node} -- chroot /host ls /sys/class/net",
                do_not_log=True,
                timeout=180,
            )
        except ShellCommandTimeoutError:
            logger.warning("Timed out listing interfaces for node %s, skipping", node)
            return []
        if code != 0:
            logger.warning("Unable to find interfaces for node %s", node)
            return []

        interfaces = []
        interfaces_list = [x.strip() for x in log.splitlines()]

        # TODO: Check which interfaces to consider for network chaos
        # For now, consider specific interfaces like ens5, eth0, etc.

        for intf in interfaces_list:
            # TODO: Check which interfaces to consider for network chaos
            # ens5, eth0, br-ex, br-int, etc. as well as other interfaces like lo, ovs-system, etc.
            # Krkn validation doesn't work with interfaces with name like ABC-XYZ
            if intf.startswith("ens") or intf.startswith("eth"):
                interfaces.append(intf)

        return interfaces

    def __fetch_node_metrics(self, node: str):
        metrics = self.custom_obj_api.list_cluster_custom_object(
            group="metrics.k8s.io", version="v1beta1", plural="nodes"
        )

        for item in metrics["items"]:
            name = item["metadata"]["name"]
            if name == node:
                usage_cpu = item["usage"]["cpu"]  # e.g. "250m"
                usage_mem = item["usage"]["memory"]  # e.g. "1024Mi"
                return self.parse_cpu(usage_cpu), self.parse_memory(usage_mem)

        raise ValueError(f"Metrics not found for node: {node}")

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
        if s.endswith("n"):  # nanocores
            n = int(s[:-1])
            return n / 1_000_000.0
        if s.endswith("u"):  # microcores
            u = int(s[:-1])
            return u / 1000.0
        if s.endswith("m"):  # millicores
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
        _mem_power2 = {
            "Ki": 1024,
            "Mi": 1024**2,
            "Gi": 1024**3,
            "Ti": 1024**4,
            "Pi": 1024**5,
            "Ei": 1024**6,
        }
        _mem_power10 = {
            "K": 1000,
            "M": 1000**2,
            "G": 1000**3,
            "T": 1000**4,
            "P": 1000**5,
            "E": 1000**6,
        }

        if mem_str is None:
            return 0
        s = str(mem_str).strip()
        if re.fullmatch(r"^\d+(\.\d+)?$", s):
            return int(float(s))
        m = re.fullmatch(r"^([0-9.]+)\s*([a-zA-Z]+)$", s)
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
