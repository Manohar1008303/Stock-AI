"""Loads config.yaml and overlays environment variables for secrets.

Single rule: everything tunable lives in config.yaml. Secrets prefer env vars.
"""
import os
import yaml
from pathlib import Path

_ENV_MAP = {
    "telegram_bot_token": "STOCKAI_TELEGRAM_TOKEN",
    "telegram_chat_id": "STOCKAI_TELEGRAM_CHAT_ID",
    "anthropic_api_key": "STOCKAI_ANTHROPIC_KEY",
    "data_provider_key": "STOCKAI_DATA_KEY",
}


class Config:
    def __init__(self, data: dict):
        self._d = data

    def __getitem__(self, key):
        return self._d[key]

    def get(self, key, default=None):
        return self._d.get(key, default)

    @property
    def raw(self):
        return self._d

    def secret(self, name: str) -> str:
        """Env var wins over yaml. Returns '' if neither is set."""
        env_key = _ENV_MAP.get(name)
        if env_key and os.environ.get(env_key):
            return os.environ[env_key].strip()
        return (self._d.get("secrets", {}).get(name) or "").strip()


def load_config(path: str = None) -> Config:
    if path is None:
        # default: config.yaml next to the project root
        path = Path(__file__).resolve().parent.parent / "config.yaml"
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found at {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    _validate(data)
    return Config(data)


def _validate(data: dict):
    required_top = ["universe", "screener", "alerts", "runtime"]
    for k in required_top:
        if k not in data:
            raise ValueError(f"config.yaml missing required section: '{k}'")
    if not data["universe"].get("symbols"):
        raise ValueError("config.yaml: universe.symbols is empty")
    sc = data["screener"]
    if sc.get("max_shortlist", 0) < 1:
        raise ValueError("config.yaml: screener.max_shortlist must be >= 1")
