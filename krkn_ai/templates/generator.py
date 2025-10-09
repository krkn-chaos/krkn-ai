import os

import jinja2
import yaml

environment = jinja2.Environment()

# Add enumerate to the template environment so it's available in templates
environment.globals['enumerate'] = enumerate


def create_krkn_ai_template(kubeconfig_file_path:str, cluster_component_data: dict) -> str:
    """Create krkn-ai.yaml from template with proper indentation"""
    # Get the directory of the current module
    current_dir = os.path.dirname(__file__)
    template_path = os.path.join(current_dir, "krkn-ai.yaml.j2")
    
    template_str = open(template_path).read()
    template = environment.from_string(template_str)

    # Convert cluster_components to properly indented YAML string
    cluster_components_yaml = yaml.dump(
        cluster_component_data, 
        default_flow_style=False, 
        indent=2,
        allow_unicode=True
    ).strip()

    # Manually indent each line by 2 spaces
    indented_lines = []
    for line in cluster_components_yaml.split('\n'):
        if line.strip():  # Only indent non-empty lines
            indented_lines.append('  ' + line)
        else:
            indented_lines.append('')  # Keep empty lines as-is
    
    cluster_components_indented = '\n'.join(indented_lines)
    
    return template.render(
        kubeconfig_file_path=kubeconfig_file_path,
        cluster_components=cluster_components_indented
    )
