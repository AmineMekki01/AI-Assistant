"""Simple logging for JARVIS Desktop"""

import logging
import sys

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger


class StructuredLog:
    """Simple structured logging."""
    
    def __init__(self, name: str):
        self.logger = get_logger(name)
    
    def info(self, event: str, **kwargs):
        msg = f"{event}"
        if kwargs:
            msg += " | " + " ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.info(msg)
    
    def error(self, event: str, **kwargs):
        msg = f"{event}"
        if kwargs:
            msg += " | " + " ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.error(msg)
    
    def debug(self, event: str, **kwargs):
        msg = f"{event}"
        if kwargs:
            msg += " | " + " ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.debug(msg)
    
    def warning(self, event: str, **kwargs):
        msg = f"{event}"
        if kwargs:
            msg += " | " + " ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.warning(msg)
