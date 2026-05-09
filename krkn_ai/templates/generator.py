import os
from typing import Any, Dict

import jinja2
import yaml

environment = jinja2.Environment()

# Add enumerate to the template environment so it's available in templates
environment.globals["enumerate"] = enumerate


def _compute_scenario_flags(cluster_component_data: dict) -> Dict[str, Any]:
    """Derive scenario availability flags from discovered cluster components.

    Inspects the serialised ``ClusterComponents`` dict and returns boolean
    flags that the Jinja2 template can use to conditionally enable or
    disable scenarios based on what actually exists in the cluster.

    Node-level destructive scenarios (``node-*-hog``, ``time-scenarios``)
    are intentionally kept disabled as safe defaults regardless of
    discovered resources.
    """
    namespaces = cluster_component_data.get("namespaces", [])
    nodes = cluster_component_data.get("nodes", [])

    has_pods = any(ns.get("pods") for ns in namespaces)
    has_services = any(ns.get("services") for ns in namespaces)
    has_pvcs = any(ns.get("pvcs") for ns in namespaces)
    has_vmis = any(ns.get("vmis") for ns in namespaces)
    has_interfaces = any(n.get("interfaces") for n in nodes)

    return {
        "has_pods": has_pods,
        "has_services": has_services,
        "has_pvcs": has_pvcs,
        "has_vmis": has_vmis,
        "has_interfaces": has_interfaces,
    }


def create_krkn_ai_template(
    kubeconfig_file_path: str, cluster_component_data: dict
) -> str:
    """Create krkn-ai.yaml from template with proper indentation"""
    # Get the directory of the current module
    current_dir = os.path.dirname(__file__)
    template_path = os.path.join(current_dir, "krkn-ai.yaml.j2")

    with open(template_path, encoding="utf-8") as f:
        template_str = f.read()
    template = environment.from_string(template_str)

    # Convert cluster_components to properly indented YAML string
    cluster_components_yaml = yaml.dump(
        cluster_component_data, default_flow_style=False, indent=2, allow_unicode=True
    ).strip()

    # Manually indent each line by 2 spaces
    indented_lines = []
    for line in cluster_components_yaml.split("\n"):
        if line.strip():  # Only indent non-empty lines
            indented_lines.append("  " + line)
        else:
            indented_lines.append("")  # Keep empty lines as-is

    cluster_components_indented = "\n".join(indented_lines)

    # Compute scenario availability flags from discovered resources
    scenario_flags = _compute_scenario_flags(cluster_component_data)

    return template.render(
        kubeconfig_file_path=kubeconfig_file_path,
        cluster_components=cluster_components_indented,
        **scenario_flags,
    )
