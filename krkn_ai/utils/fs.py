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
        existing = config.get("parameters")
        if isinstance(existing, dict):
            for k, v in existing.items():
                params[str(k)] = ParameterValue.from_cli(str(k), str(v))

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

        # Replace parameters in elastic configuration without forcing optional keys.
        if isinstance(config.get("elastic"), dict):
            bool_fields = {"enable", "verify_certs"}
            for key, value in config["elastic"].items():
                if isinstance(value, str):
                    value = preprocess_param_string(value, raw)
                config["elastic"][key] = (
                    is_truthy(value)
                    if key in bool_fields and value is not None
                    else value
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


def _merge_fitness_items(raw: dict, fitness_queries: list = None) -> None:
    """Add newly recommended enabled fitness items, keeping the user's existing ones."""
    if not fitness_queries:
        return
    ff = raw.setdefault("fitness_function", {})
    items = ff.get("items") or []
    seen = {item.get("query") for item in items}
    for f in fitness_queries:
        if f.get("enabled") and f["query"] not in seen:
            items.append(
                {"query": f["query"], "type": f["type"], "weight": f["weight"]}
            )
            seen.add(f["query"])
    if items:
        ff["items"] = items


def _build_merged_config(
    output: str,
    discovered: ClusterComponents,
    kubeconfig: str,
    fitness_queries: list = None,
) -> Union[str, None]:
    """Merge discovered components into the existing config, keeping the user's
    edits."""
    try:
        config = read_config_from_file(output, kubeconfig=kubeconfig)
    except (yaml.YAMLError, ValueError, ValidationError) as e:
        logger.warning(
            "Could not read existing config %s (%s); leaving file unchanged.",
            output,
            e,
        )
        return None
    # edit the raw file so user fields aren't dropped on a model dump
    with open(output, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    merged = merge_components(config.cluster_components, discovered)
    raw["cluster_components"] = merged.model_dump(
        mode="json", warnings="none", exclude_defaults=True
    )
    _merge_fitness_items(raw, fitness_queries)
    return yaml.safe_dump(
        raw, default_flow_style=False, sort_keys=False, allow_unicode=True
    )


def _write_fresh(
    output: str,
    components: ClusterComponents,
    kubeconfig: str,
    scenario_enables: dict = None,
    fitness_queries: list = None,
    health_checks: list = None,
):
    """Write fresh config from discovered components."""
    data = components.model_dump(mode="json", warnings="none", exclude_defaults=True)
    template = create_krkn_ai_template(
        kubeconfig,
        data,
        scenario_enables,
        health_checks=health_checks,
        fitness_queries=fitness_queries,
    )
    with open(output, "w", encoding="utf-8") as f:
        f.write(template)
    logger.info("Saved component configuration to %s", output)


def save_discovery(
    output: str,
    strategy: str,
    components: ClusterComponents,
    kubeconfig: str,
    scenario_enables: dict = None,
    fitness_queries: list = None,
    health_checks: list = None,
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
        text = _build_merged_config(output, components, kubeconfig, fitness_queries)
        if text is None:
            return
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info("Merged discovered components into %s", output)
        return

    if exists and strategy == "overwrite":
        logger.warning("Overwriting existing %s", output)

    _write_fresh(
        output,
        components,
        kubeconfig,
        scenario_enables,
        fitness_queries,
        health_checks,
    )
