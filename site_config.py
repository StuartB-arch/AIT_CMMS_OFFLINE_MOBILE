"""
site_config.py — Per-site configuration for AIT CMMS
Stores site name and CSV file paths in site_config.json so each
installation can point to its own asset and MRO stock files.
"""
import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "site_config.json"


def load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(config: dict):
    with open(_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)


def get(key: str, default=None):
    return load_config().get(key, default)


def set_value(key: str, value):
    config = load_config()
    config[key] = value
    save_config(config)


def get_pm_csv_path() -> Path | None:
    p = get('pm_csv_path')
    return Path(p) if p else None


def get_mro_csv_path() -> Path | None:
    p = get('mro_csv_path')
    return Path(p) if p else None


def get_site_name() -> str:
    return get('site_name', '')
