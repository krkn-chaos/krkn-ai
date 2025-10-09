import json
import os
import yaml
from typing import Union, Any, List, Dict

from krkn_ai.models.config import ConfigFile
from krkn_ai.utils.logger import get_module_logger

logger = get_module_logger(__name__)


def preprocess_param_string(data: str, params: dict) -> str:
    '''
    Preprocess the health check url to replace the parameters with the values.
    '''
    for k,v in params.items():
        data = data.replace(f'${k}', v)
    return data


def read_config_from_file(file_path: str, param: list[str] = None) -> ConfigFile:
    """Read config file from local
    Args:
        file_path: Path to config file
        param: Additional parameters for config file in key=value format.
    Returns:
        ConfigFile: Config file object
    """
    with open(file_path, "r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if param:
        # Keep track of parameters in config file
        config['parameters'] = {}
        for p in param:
            key, value = p.split('=')
            config['parameters'][str(key)] = str(value)

        # Replace parameter in health check url string
        if 'health_checks' in config and 'applications' in config['health_checks']:
            for health_check in config['health_checks']['applications']:
                health_check['url'] = preprocess_param_string(health_check['url'], config['parameters'])
    return ConfigFile(**config)


def env_is_truthy(var: str):
    '''
    Checks whether a environment variable is set to truthy value.
    '''
    value = os.getenv(var, 'false')
    value = value.lower().strip()
    return value in ['yes', 'y', 'true', '1']


def save_data_to_file(data: Union[Dict, List], file_path: str):
    format = file_path.split('.')[-1]
    if format == 'yaml':
        with open(file_path, 'w') as f:
            yaml.dump(data, f)
    elif format == 'json':
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)
    else:
        raise ValueError(f"Unsupported format: {format}")
