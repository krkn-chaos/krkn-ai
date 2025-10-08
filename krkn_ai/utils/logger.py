import click
import logging
from typing import Optional

# Global variable to store the current log level
_GLOBAL_LOG_LEVEL = logging.INFO

def verbosity_to_level(verbosity: int) -> int:
    if verbosity == 0:
        return logging.INFO
    else:
        return logging.DEBUG

def set_global_log_level(level: int):
    """Set the global log level that will be used by all loggers"""
    global _GLOBAL_LOG_LEVEL
    _GLOBAL_LOG_LEVEL = level
    
    # Update all existing loggers
    for name in logging.Logger.manager.loggerDict:
        logger = logging.getLogger(name)
        if logger.handlers:  # Only update loggers that have been configured by us
            logger.setLevel(level)

def get_module_logger(mod_name: str, log_level: Optional[int] = None):
    '''Main Logging module'''
    global _GLOBAL_LOG_LEVEL
    
    # Try to get log level from various sources in order of priority
    if log_level is not None:
        level = log_level
    else:
        try:
            ctx = click.get_current_context()
            level = ctx.obj.verbose if ctx and hasattr(ctx.obj, 'verbose') else _GLOBAL_LOG_LEVEL
        except RuntimeError:
            level = _GLOBAL_LOG_LEVEL

    logger = logging.getLogger(mod_name)
    
    # Only add handler if logger doesn't already have one
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False  # Prevent duplicate messages
    
    logger.setLevel(level)
    return logger
