from typing import Dict, List, Optional, Set, Tuple, Union
from pydantic import BaseModel, PrivateAttr


class Container(BaseModel):
    name: str
    disabled: bool = False


class OwnerReference(BaseModel):
    kind: str
    name: str


class Pod(BaseModel):
    name: str
    labels: Dict[str, str] = {}
    containers: List[Container] = []
    owner: Optional[OwnerReference] = None
    disabled: bool = False


class PVC(BaseModel):
    name: str
    labels: Dict[str, str] = {}
    current_usage_percentage: Optional[float] = None
    disabled: bool = False


class ServicePort(BaseModel):
    port: int
    target_port: Optional[Union[int, str]] = None
    protocol: str = "TCP"


class Service(BaseModel):
    name: str
    labels: Dict[str, str] = {}
    ports: List[ServicePort] = []
    disabled: bool = False


class VMI(BaseModel):
    name: str
    disabled: bool = False


class Namespace(BaseModel):
    name: str
    pods: List[Pod] = []
    services: List[Service] = []
    pvcs: List[PVC] = []
    vmis: List[VMI] = []
    disabled: bool = False
    # (label, value, container) of the containers dropped by get_active_components
    _disabled_containers: Set[Tuple[str, str, str]] = PrivateAttr(default=set())

    def can_target_container(self, pod: Pod, label: str, container: str) -> bool:
        """Whether no pod sharing this label has the container disabled. Krkn
        picks among all the pods matching the label."""
        return (label, pod.labels[label], container) not in self._disabled_containers


class Node(BaseModel):
    name: str
    labels: Dict[str, str] = {}
    free_cpu: float = 0
    free_mem: float = 0
    interfaces: List[str] = []
    taints: List[str] = []
    disabled: bool = False


class ClusterComponents(BaseModel):
    namespaces: List[Namespace] = []
    nodes: List[Node] = []
    _has_disabled_nodes: bool = PrivateAttr(default=False)

    @property
    def has_disabled_nodes(self) -> bool:
        return self._has_disabled_nodes or any(node.disabled for node in self.nodes)

    def get_active_components(self) -> "ClusterComponents":
        """
        Returns a new ClusterComponents instance with disabled items filtered out.
        This provides a centralized way to filter disabled components for all scenarios.
        """
        active_namespaces = []
        for ns in self.namespaces:
            if ns.disabled:
                continue
            # Create a copy of namespace with filtered sub-components
            active_ns = Namespace(
                name=ns.name,
                pods=[
                    p.model_copy(
                        update={
                            "containers": [c for c in p.containers if not c.disabled]
                        }
                    )
                    if any(c.disabled for c in p.containers)
                    else p
                    for p in ns.pods
                    if not p.disabled
                ],
                services=[s for s in ns.services if not s.disabled],
                pvcs=[pvc for pvc in ns.pvcs if not pvc.disabled],
                vmis=[vmi for vmi in ns.vmis if not vmi.disabled],
                disabled=ns.disabled,
            )
            active_ns._disabled_containers = ns._disabled_containers | {
                (label, value, c.name)
                for p in ns.pods
                for c in p.containers
                if c.disabled or p.disabled
                for label, value in p.labels.items()
            }
            active_namespaces.append(active_ns)

        active_nodes = [n for n in self.nodes if not n.disabled]

        active = ClusterComponents(namespaces=active_namespaces, nodes=active_nodes)
        active._has_disabled_nodes = self._has_disabled_nodes or len(
            active_nodes
        ) < len(self.nodes)
        return active
