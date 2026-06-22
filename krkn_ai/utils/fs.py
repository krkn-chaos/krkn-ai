import json
import os
import yaml
from collections.abc import Sequence
from typing import Union, List, Dict

from pydantic import ValidationError

from krkn_ai.models.config import ConfigFile, ParameterValue
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.templates.generator import create_krkn_ai_template
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


def preprocess_param_string(data: str, params: dict) -> str:
    """
    Preprocess the health check url to replace the parameters with the values.
    """
    data = str(data)
    for k, v in params.items():
        data = data.replace(f"${k}", v)
    return data


def read_config_from_file(
    file_path: str,
    param: Union[Sequence[str], None] = None,
    kubeconfig: Union[str, None] = None,
) -> ConfigFile:
    """Read config file from local
    Args:
        file_path: Path to config file
        param: Additional parameters for config file in key=value format.
    Returns:
        ConfigFile: Config file object
    """
    with open(file_path, "r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if config is None:
        config = {}

    if not isinstance(config, dict):
        raise ValueError(
            f"Config file {file_path} must be a mapping (dictionary), "
            f"but found {type(config).__name__}."
        )

    if kubeconfig is not None and kubeconfig != "" and os.path.exists(kubeconfig):
        config["kubeconfig_file_path"] = kubeconfig

    # param refers to Key-value passed with -p flag during krkn-ai test run
    if param:
        params = {}
        for p in param:
            if "=" in p:
                key, value = p.split("=", 1)
            else:
                key, value = p, ""
            params[str(key)] = ParameterValue.from_cli(str(key), str(value))

        raw = {k: v.value for k, v in params.items()}

        # Replace parameter in health check url string
        for app in config.get("health_checks", {}).get("applications", []):
            if "url" in app:
                app["url"] = preprocess_param_string(app["url"], raw)

        # Replace parameter in elastic configuration
        if "elastic" in config and "server" in config["elastic"]:
            config["elastic"]["enable"] = is_truthy(
                preprocess_param_string(config["elastic"]["enable"], raw)
            )
            config["elastic"]["verify_certs"] = is_truthy(
                preprocess_param_string(config["elastic"]["verify_certs"], raw)
            )
            config["elastic"]["server"] = preprocess_param_string(
                config["elastic"]["server"], raw
            )
            config["elastic"]["port"] = preprocess_param_string(
                config["elastic"]["port"], raw
            )
            config["elastic"]["username"] = preprocess_param_string(
                config["elastic"]["username"], raw
            )
            config["elastic"]["password"] = preprocess_param_string(
                config["elastic"]["password"], raw
            )
            config["elastic"]["index"] = preprocess_param_string(
                config["elastic"]["index"], raw
            )

        config["parameters"] = params

    return ConfigFile.model_validate(config)


def env_is_truthy(var: str) -> bool:
    """
    Checks whether a environment variable is set to truthy value.
    """
    value = os.getenv(var, "false")
    return is_truthy(value)


def is_truthy(value: Union[str, bool, int]) -> bool:
    """
    Checks whether a value is set to truthy value.
    """
    value = str(value).lower().strip()
    return value in ["yes", "y", "true", "1"]


def save_data_to_file(data: Union[Dict, List], file_path: str):
    format = file_path.split(".")[-1]
    if format == "yaml":
        with open(file_path, "w") as f:
            yaml.dump(data, f)
    elif format == "json":
        with open(file_path, "w") as f:
            json.dump(data, f, indent=4)
    else:
        raise ValueError(f"Unsupported format: {format}")


def _indent_block(text: str) -> str:
    """Indent text by 2 spaces for YAML nesting."""
    lines = []
    for line in text.split("\n"):
        if line.strip():
            lines.append("  " + line)
        else:
            lines.append("")
    return "\n".join(lines)


def _render_components_block(components: ClusterComponents) -> str:
    """Convert components to YAML block."""
    data = components.model_dump(mode="json", warnings="none", exclude_defaults=True)
    body = yaml.dump(
        data, default_flow_style=False, indent=2, allow_unicode=True, sort_keys=False
    ).strip()
    return "cluster_components:\n" + _indent_block(body)


def _cluster_components_block(text: str) -> str:
    """Extract cluster_components block from file."""
    out, capturing = [], False
    for line in text.splitlines():
        if line.startswith("cluster_components:"):
            capturing = True
            out.append(line)
            continue
        if capturing:
            if line and not line[0].isspace():
                break
            out.append(line)
    return "\n".join(out).rstrip()


def _union_by_name(existing: list, discovered: list) -> list:
    """Union two lists by name, keep existing items."""
    by_name = {item.name: item for item in existing}
    for item in discovered:
        if item.name not in by_name:
            by_name[item.name] = item
    return list(by_name.values())


def merge_components(
    existing: ClusterComponents, discovered: ClusterComponents
) -> ClusterComponents:
    """Merge existing and discovered components, preserving edits."""
    namespaces = {ns.name: ns for ns in existing.namespaces}
    for ns in discovered.namespaces:
        current = namespaces.get(ns.name)
        if current is None:
            namespaces[ns.name] = ns
            continue
        current.pods = _union_by_name(current.pods, ns.pods)
        current.services = _union_by_name(current.services, ns.services)
        current.pvcs = _union_by_name(current.pvcs, ns.pvcs)
        current.vmis = _union_by_name(current.vmis, ns.vmis)
    nodes = _union_by_name(existing.nodes, discovered.nodes)
    return ClusterComponents(namespaces=list(namespaces.values()), nodes=nodes)


def _build_merged_config(output: str, discovered: ClusterComponents) -> str:
    """Build file content with merged components block."""
    with open(output, "r", encoding="utf-8") as f:
        existing_text = f.read()

    existing_block = _cluster_components_block(existing_text)
    if not existing_block:
        logger.warning(
            "No cluster_components section found in %s; appending discovered components.",
            output,
        )
        return (
            existing_text.rstrip("\n")
            + "\n\n"
            + _render_components_block(discovered)
            + "\n"
        )

    try:
        block_data = yaml.safe_load(existing_block) or {}
    except yaml.YAMLError as e:
        logger.warning(
            "Could not parse cluster_components in %s (%s); leaving file unchanged.",
            output,
            e,
        )
        return existing_text

    try:
        existing = ClusterComponents.model_validate(
            block_data.get("cluster_components", {}) or {}
        )
    except ValidationError as e:
        logger.warning(
            "Invalid cluster_components in %s (%s); leaving file unchanged.",
            output,
            e,
        )
        return existing_text
    merged = merge_components(existing, discovered)
    return existing_text.replace(existing_block, _render_components_block(merged))


def _write_fresh(output: str, components: ClusterComponents, kubeconfig: str):
    """Write fresh config from discovered components."""
    data = components.model_dump(mode="json", warnings="none", exclude_defaults=True)
    template = create_krkn_ai_template(kubeconfig, data)
    with open(output, "w", encoding="utf-8") as f:
        f.write(template)
    logger.info("Saved component configuration to %s", output)


def save_discovery(
    output: str,
    strategy: str,
    components: ClusterComponents,
    kubeconfig: str,
):
    """Save discovered components per strategy: skip (do nothing), overwrite (replace), or merge (add new)."""
    strategy = strategy.lower()
    exists = os.path.exists(output)

    if exists and strategy == "skip":
        logger.warning(
            "%s already exists; skipping write "
            "(use --save-strategy overwrite or merge to change this).",
            output,
        )
        return

    if exists and strategy == "merge":
        text = _build_merged_config(output, components)
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info("Merged discovered components into %s", output)
        return

    if exists and strategy == "overwrite":
        logger.warning("Overwriting existing %s", output)

    _write_fresh(output, components, kubeconfig)
