"""Resolve repo root for notebooks and scripts under ``analysis/``."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
