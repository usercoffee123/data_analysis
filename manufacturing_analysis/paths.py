"""Resolve repository resources independently of the current working directory."""

from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
CONFIG_DIR = PROJECT_DIR / "config"
REPORTS_DIR = PROJECT_DIR / "reports"
