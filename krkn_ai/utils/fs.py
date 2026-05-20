import json
import os
import stat
import uuid
import yaml
from typing import Union, List, Dict, Callable, Optional, cast

from krkn_ai.models.config import ConfigFile, ParameterValue
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


def _fsync_directory(dir_path: str):
    try:
        dir_fd = os.open(dir_path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def _existing_file_mode(file_path: str) -> int:
    try:
        return stat.S_IMODE(os.stat(file_path).st_mode)
    except FileNotFoundError:
        return 0o666


def _preserve_existing_metadata(source_path: str, target_path: str):
    try:
        source_stat = os.stat(source_path)
    except FileNotFoundError:
        return

    if hasattr(os, "chown"):
        try:
            os.chown(target_path, source_stat.st_uid, source_stat.st_gid)
        except OSError:
            logger.debug("Unable to preserve ownership for %s", target_path)

    try:
        os.chmod(target_path, stat.S_IMODE(source_stat.st_mode))
    except OSError:
        logger.debug("Unable to preserve mode for %s", target_path)

    _preserve_existing_xattrs(source_path, target_path)


def _preserve_existing_xattrs(source_path: str, target_path: str):
    listxattr = cast(
        Optional[Callable[[str], List[str]]], getattr(os, "listxattr", None)
    )
    getxattr = cast(
        Optional[Callable[[str, str], bytes]], getattr(os, "getxattr", None)
    )
    setxattr = cast(
        Optional[Callable[[str, str, bytes], None]], getattr(os, "setxattr", None)
    )
    if listxattr is None or getxattr is None or setxattr is None:
        return

    try:
        xattr_names = listxattr(source_path)
    except OSError:
        return

    for name in xattr_names:
        try:
            setxattr(target_path, name, getxattr(source_path, name))
        except OSError:
            logger.debug(
                "Unable to preserve extended attribute %s for %s", name, target_path
            )


def atomic_write_text(file_path: str, data: str):
    """
    Write text to a file using a same-directory temporary file and atomic replace.
    """
    target_path = os.path.realpath(file_path)
    output_dir = os.path.dirname(target_path)
    base_name = os.path.basename(target_path)
    tmp_path = os.path.join(output_dir, f".{base_name}.{uuid.uuid4().hex}.tmp")
    tmp_mode = _existing_file_mode(target_path)

    fd = None
    tmp_created = False
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, tmp_mode)
        tmp_created = True
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        _preserve_existing_metadata(target_path, tmp_path)
        os.replace(tmp_path, target_path)
        _fsync_directory(output_dir)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                logger.debug("Unable to close temporary file %s", tmp_path)
        try:
            if tmp_created and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            logger.debug("Unable to remove temporary file %s", tmp_path)
        raise


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
