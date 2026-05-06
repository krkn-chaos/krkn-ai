import json
import os
import yaml
from typing import Union, List, Dict

from krkn_ai.models.config import ConfigFile
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
    file_path: str, param: list[str] = None, kubeconfig: str = None
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
            params[str(key)] = str(value)

        # Replace parameter in health check url string
        if "health_checks" in config and "applications" in config["health_checks"]:
            for health_check in config["health_checks"]["applications"]:
                health_check["url"] = preprocess_param_string(
                    health_check["url"], params
                )

        # Replace parameter in elastic configuration
        if "elastic" in config and "server" in config["elastic"]:
            config["elastic"]["enable"] = is_truthy(
                preprocess_param_string(config["elastic"]["enable"], params)
            )
            config["elastic"]["verify_certs"] = is_truthy(
                preprocess_param_string(config["elastic"]["verify_certs"], params)
            )
            config["elastic"]["server"] = preprocess_param_string(
                config["elastic"]["server"], params
            )
            config["elastic"]["port"] = preprocess_param_string(
                config["elastic"]["port"], params
            )
            config["elastic"]["username"] = preprocess_param_string(
                config["elastic"]["username"], params
            )
            config["elastic"]["password"] = preprocess_param_string(
                config["elastic"]["password"], params
            )
            config["elastic"]["index"] = preprocess_param_string(
                config["elastic"]["index"], params
            )

        # Remove private parameters from config (starts with double __underscore)
        config["parameters"] = {
            k: v for k, v in params.items() if not k.startswith("__")
        }

    return ConfigFile(**config)


def env_is_truthy(var: str):
    """
    Checks whether a environment variable is set to truthy value.
    """
    value = os.getenv(var, "false")
    return is_truthy(value)


def is_truthy(value: str):
    """
    Checks whether a value is set to truthy value.
    """
    value = value.lower().strip()
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
