from typing import Dict, List, Optional, Union
from pydantic import BaseModel


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
                pods=[p for p in ns.pods if not p.disabled],
                services=[s for s in ns.services if not s.disabled],
                pvcs=[pvc for pvc in ns.pvcs if not pvc.disabled],
                vmis=[vmi for vmi in ns.vmis if not vmi.disabled],
                disabled=ns.disabled,
            )
            active_namespaces.append(active_ns)

        active_nodes = [n for n in self.nodes if not n.disabled]

        return ClusterComponents(namespaces=active_namespaces, nodes=active_nodes)
