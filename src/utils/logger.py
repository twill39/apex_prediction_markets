"""Logging utilities"""

import logging
import os
from pathlib import Path
from typing import Optional
from src.config import get_settings


def setup_logger(name: str = "trading_fund", log_file: Optional[str] = None) -> logging.Logger:
    """Set up and configure logger"""
    settings = get_settings()
    
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.logging.level.upper(), logging.INFO))
    
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
        
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger


# Global logger instance
_logger: Optional[logging.Logger] = None


def get_logger(name: str = "trading_fund") -> logging.Logger:
    """Get or create global logger instance"""
    global _logger
    if _logger is None:
        _logger = setup_logger(name)
    return _logger
