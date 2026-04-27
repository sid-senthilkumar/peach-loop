"""Configuration loading and merging.

Configs are YAML files.  The base config sets defaults; phase configs override them.
Merging is a simple recursive dict update, not a schema validator — intentionally
simple for a learning project.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class Config:
    """Dot-access wrapper around a nested dict loaded from YAML.

    Usage::

        cfg = load_config("configs/base.yaml", "configs/phase1.yaml")
        print(cfg.peach.n_epochs)         # 150
        print(cfg.paths.checkpoints)      # "checkpoints"
    """

    def __init__(self, data: dict):
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, Config(value))
            elif isinstance(value, list):
                setattr(self, key, [Config(v) if isinstance(v, dict) else v for v in value])
            else:
                setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict:
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Config):
                result[key] = value.to_dict()
            elif isinstance(value, list):
                result[key] = [v.to_dict() if isinstance(v, Config) else v for v in value]
            else:
                result[key] = value
        return result

    def __repr__(self) -> str:
        return f"Config({list(self.__dict__.keys())})"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(*yaml_paths: str | Path) -> Config:
    """Load one or more YAML files, merging later ones over earlier ones.

    The first path is treated as the base; each subsequent path overrides it.
    Relative paths are resolved from the repository root (parent of src/).
    """
    # Resolve repo root from this file's location: src/peach_loop/config.py → ../../
    repo_root = Path(__file__).parent.parent.parent

    merged: dict = {}
    for path in yaml_paths:
        full_path = Path(path) if Path(path).is_absolute() else repo_root / path
        with open(full_path) as f:
            data = yaml.safe_load(f) or {}
        merged = _deep_merge(merged, data)

    return Config(merged)


def default_config() -> Config:
    """Load base + phase1 config — convenient for single-phase runs."""
    return load_config("configs/base.yaml", "configs/phase1.yaml")


def resolve_path(cfg: Config, key: str) -> Path:
    """Return an absolute Path for a path key in cfg.paths, creating dirs if needed."""
    repo_root = Path(os.environ.get("PEACH_LOOP_ROOT", Path(__file__).parent.parent.parent))
    raw = getattr(cfg.paths, key, key)
    p = Path(raw) if Path(raw).is_absolute() else repo_root / raw
    p.mkdir(parents=True, exist_ok=True)
    return p
