import os
from typing import Dict, List

import jinja2
import yaml

environment = jinja2.Environment()

# Add enumerate to the template environment so it's available in templates
environment.globals["enumerate"] = enumerate


def create_krkn_ai_template(
    kubeconfig_file_path: str,
    cluster_component_data: dict,
    health_check_urls: List[Dict[str, str]] = None,
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

    # Build health_checks YAML block
    health_checks_yaml = ""
    if health_check_urls:
        health_checks_data = {
            "health_checks": {
                "stop_watcher_on_failure": False,
                "applications": [
                    {"name": entry["name"], "url": entry["url"]}
                    for entry in health_check_urls
                ],
            }
        }
        health_checks_yaml = yaml.dump(
            health_checks_data,
            default_flow_style=False,
            indent=2,
            allow_unicode=True,
        ).strip()

    return template.render(
        kubeconfig_file_path=kubeconfig_file_path,
        cluster_components=cluster_components_indented,
        health_checks=health_checks_yaml,
    )
