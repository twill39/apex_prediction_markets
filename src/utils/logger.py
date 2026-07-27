"""Logging utilities"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional
from src.config import get_settings


def setup_logger(name: str = "trading_fund", log_file: Optional[str] = None) -> logging.Logger:
    """Set up and configure logger"""
    settings = get_settings()
    
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.logging.level.upper(), logging.INFO))
    logger.propagate = False
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler
    log_path = log_file or settings.logging.file
    if log_path:
        # Create log directory if it doesn't exist
        log_dir = Path(log_path).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max(int(settings.logging.max_bytes), 1024),
            backupCount=max(int(settings.logging.backup_count), 1),
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger


# Component loggers share configuration but preserve their own names.
_loggers: Dict[str, logging.Logger] = {}


def get_logger(name: str = "trading_fund") -> logging.Logger:
    """Get or create a configured component logger."""
    if name not in _loggers:
        _loggers[name] = setup_logger(name)
    return _loggers[name]
