import re
import ipaddress
import concurrent.futures
from typing import Dict, List, Optional, Union

import requests
from krkn_lib.k8s.krkn_kubernetes import KrknKubernetes
from kubernetes.client.models import V1PodSpec
from krkn_ai.utils import run_shell
from krkn_ai.utils.logger import get_logger
from krkn_ai.models.custom_errors import ShellCommandTimeoutError
from krkn_ai.cluster.pattern_matcher import PatternMatcher
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

# Network interface name prefixes that are valid targets for network chaos.
# Covers classic and predictable NIC names, bonds, bridges, InfiniBand and
# wireless across bare-metal, cloud and OpenShift nodes. (#294)
_TARGETABLE_INTERFACE_PREFIXES = (
    "eth",  # classic: eth0
    "en",  # predictable names: ens5, eno1, enp0s3, enx001122334455
    "em",  # onboard (older biosdevname): em1
    "bond",  # link aggregation: bond0
    "br",  # bridges: br-ex, br0, bridge0
    "ib",  # InfiniBand: ib0
    "wlan",  # wireless: wlan0
)

# biosdevname-style PCI NICs (e.g. p2p1, p1p1). Matched separately from the
# prefix tuple so a bare "p" doesn't admit non-physical names like "ppp0". (#294)
_PCI_INTERFACE_RE = re.compile(r"^p\d")

# Virtual / internal interfaces that must never be disrupted, even when they
# share a prefix with a targetable one (e.g. "podman0" starts with "p", and the
# OVS/OVN internal bridges "br-int"/"br-tun" start with "br"). Exclusion takes
# precedence over the whitelist above. (#294)
_EXCLUDED_INTERFACE_PREFIXES = (
    "lo",  # loopback
    "veth",  # container virtual ethernet pairs
    "ovs",  # Open vSwitch: ovs-system
    "br-int",  # OVN/OVS integration bridge (pod-to-pod traffic)
    "br-tun",  # OVS tunnel bridge (overlay traffic)
    "docker",  # docker bridge: docker0
    "podman",  # podman bridge: podman0
    "cni",  # CNI plugin interfaces: cni0
    "flannel",  # flannel.1
    "cali",  # Calico: cali<hash>
    "tunl",  # IPIP tunnels: tunl0
    "vxlan",  # VXLAN overlays: vxlan.calico
    "dummy",  # dummy interfaces
)


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

    def recommend_health_checks(
        self, cluster_components: ClusterComponents
    ) -> List[Dict[str, Union[str, bool]]]:
        """Suggest health-check URLs for LoadBalancer services."""
        try:
            recommendations: List[Dict[str, Union[str, bool]]] = []
            for namespace in cluster_components.get_active_components().namespaces:
                services = self.core_api.list_namespaced_service(
                    namespace=namespace.name
                ).items
                pods = self.core_api.list_namespaced_pod(
                    namespace=namespace.name, field_selector="status.phase=Running"
                ).items

                for svc in services:
                    if svc.spec.type != "LoadBalancer" or not svc.spec.ports:
                        continue
                    address = self._external_address(svc)
                    if address is None:
                        continue

                    probe, container = self._backing_probe(svc, pods)
                    port, scheme, path = self._endpoint_from_probe(
                        svc, probe, container
                    )
                    host = self._format_host(address)
                    url = f"{scheme}://{host}:{port}{path}"
                    recommendations.append(
                        {
                            "name": svc.metadata.name,
                            "url": url,
                            "probe": probe is not None,
                            "active": self._check_reachable(url),
                        }
                    )
            return recommendations
        except Exception as error:
            # Never let this break discovery.
            logger.debug("Health check recommendation failed: %s", error)
            return []

    @staticmethod
    def _external_address(svc) -> Optional[str]:
        # The LoadBalancer's external IP or hostname.
        if not svc.status or not svc.status.load_balancer:
            return None
        for entry in svc.status.load_balancer.ingress or []:
            if entry.ip or entry.hostname:
                return entry.ip or entry.hostname
        return None

    @staticmethod
    def _format_host(address: str) -> str:
        # Wrap IPv6 literals in brackets so the URL stays valid.
        try:
            if isinstance(ipaddress.ip_address(address), ipaddress.IPv6Address):
                return f"[{address}]"
        except ValueError:
            pass
        return address

    @staticmethod
    def _check_reachable(url: str) -> bool:
        try:
            resp = requests.get(url, timeout=3, verify=False)
            return resp.status_code < 500
        except Exception:
            return False

    def _backing_probe(self, svc, pods):
        # First httpGet probe behind the service, preferring readiness over
        # liveness across all containers.
        selector = svc.spec.selector or {}
        if not selector:
            return None, None
        for pod in pods:
            labels = pod.metadata.labels or {}
            if not all(labels.get(key) == value for key, value in selector.items()):
                continue
            for attr in ("readiness_probe", "liveness_probe"):
                for container in pod.spec.containers:
                    probe = getattr(container, attr)
                    if probe and probe.http_get:
                        return probe.http_get, container
        return None, None

    @staticmethod
    def _endpoint_from_probe(svc, probe, container):
        # Match the probe's port to a service port; else the first port at root.
        port = svc.spec.ports[0].port
        path = "/"
        scheme = None
        probe_port = (
            ClusterManager._resolve_port(probe.port, container)
            if probe is not None
            else None
        )
        if probe_port is not None:
            for svc_port in svc.spec.ports:
                target = svc_port.target_port
                target = svc_port.port if target is None else target
                if ClusterManager._resolve_port(target, container) == probe_port:
                    port = svc_port.port
                    path = probe.path or "/"
                    scheme = (probe.scheme or "HTTP").lower()
                    break
        if scheme is None:
            scheme = "https" if port in (443, 8443) else "http"
        return port, scheme, path

    @staticmethod
    def _resolve_port(value, container):
        # Turn an int or named port into a port number.
        if isinstance(value, int):
            return value
        for port in container.ports or []:
            if port.name == value:
                return port.container_port
        return None

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
        except Exception as e:
            logger.warning(
                "Unable to find VMIs in namespace %s: %s",
                namespace.name,
                e,
                exc_info=True,
            )
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

        # Fetch all node metrics in a single API call (O(1) network request)
        # and build a lookup dictionary for O(1) per-node access.
        node_metrics_map: Dict[str, tuple] = {}
        try:
            metrics = self.custom_obj_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="nodes"
            )
            for item in metrics.get("items", []):
                name = item["metadata"]["name"]
                usage_cpu = self.parse_cpu(item["usage"]["cpu"])
                usage_mem = self.parse_memory(item["usage"]["memory"])
                node_metrics_map[name] = (usage_cpu, usage_mem)
        except Exception as e:
            logger.warning("Failed to fetch cluster node metrics: %s", e)

        def process_node(node):
            # Check whether node is unschedulable
            if node.spec.unschedulable:
                logger.debug("Node %s is unschedulable, skipping", node.metadata.name)
                return None
            # Check whether node is not Ready
            is_ready = False
            for condition in node.status.conditions:
                if condition.type == "Ready" and condition.status == "True":
                    is_ready = True
                    break
            if not is_ready:
                logger.debug("Node %s is not Ready, skipping", node.metadata.name)
                return None

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
                alloc_cpu = self.parse_cpu(node.status.allocatable["cpu"])
                alloc_mem = self.parse_memory(node.status.allocatable["memory"])
                if node.metadata.name not in node_metrics_map:
                    raise ValueError(
                        f"Metrics not found for node: {node.metadata.name}"
                    )
                usage_cpu, usage_mem = node_metrics_map[node.metadata.name]
                node_component.free_cpu = alloc_cpu - usage_cpu
                node_component.free_mem = alloc_mem - usage_mem
            except Exception as e:
                node_component.free_cpu = -1  # -1 means not available
                node_component.free_mem = -1  # -1 means not available
                logger.warning(
                    "Failed to fetch node metrics for node %s: %s",
                    node.metadata.name,
                    e,
                )
            return node_component

        node_list = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(process_node, node) for node in nodes]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result is not None:
                    node_list.append(result)

        if node_list:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future_to_node = {
                    executor.submit(self.list_node_interfaces, node.name): node
                    for node in node_list
                }
                for future in concurrent.futures.as_completed(future_to_node):
                    node = future_to_node[future]
                    try:
                        node.interfaces = future.result()
                    except Exception as e:
                        logger.error(
                            "Failed to list node interfaces for node %s: %s",
                            node.name,
                            e,
                        )

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

        interfaces_list = [x.strip() for x in log.splitlines()]

        # Keep only physical/targetable interfaces; drop virtual and internal
        # ones (loopback, veth pairs, overlay/bridge interfaces created by
        # container runtimes and CNIs) so chaos never disrupts core networking.
        interfaces = [
            intf for intf in interfaces_list if self._is_targetable_interface(intf)
        ]

        return interfaces

    @staticmethod
    def _is_targetable_interface(name: str) -> bool:
        """Return True if ``name`` is a physical/targetable network interface.

        Excluded virtual/internal interfaces take precedence over the targetable
        whitelist, so names that share a prefix with a real NIC (e.g. "podman0"
        vs the "p" prefix) are still filtered out. (#294)
        """
        if not name or name.startswith(_EXCLUDED_INTERFACE_PREFIXES):
            return False
        if name.startswith(_TARGETABLE_INTERFACE_PREFIXES):
            return True
        # biosdevname PCI NICs (p2p1, p1p1) but not names like "ppp0".
        return bool(_PCI_INTERFACE_RE.match(name))

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
        if u_uc in _mem_power10:
            return int(val * _mem_power10[u_uc])
        raise ValueError(f"Unknown memory unit: {unit}")
