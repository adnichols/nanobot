"""Configuration loading utilities."""

import copy
import json
from pathlib import Path

from pydantic import ValidationError

from nanobot.config.schema import Config


def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".nanobot" / "config.json"


def get_data_dir() -> Path:
    """Get the nanobot data directory."""
    from nanobot.utils.helpers import get_data_path

    return get_data_path()


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            config, ignored_paths = _load_config_lenient(data)
            if ignored_paths:
                joined = ", ".join(".".join(str(part) for part in path) for path in ignored_paths)
                print(f"Warning: Ignoring unknown config keys from {path}: {joined}")
            return config
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data


def _load_config_lenient(data: dict) -> tuple[Config, list[tuple[str | int, ...]]]:
    """Load config while pruning only unknown keys from newer config versions."""
    sanitized = copy.deepcopy(data)
    ignored_paths: list[tuple[str | int, ...]] = []

    while True:
        try:
            return Config.model_validate(sanitized), ignored_paths
        except ValidationError as exc:
            extra_paths = _collect_extra_paths(exc)
            if not extra_paths:
                raise

            removed_any = False
            for path in extra_paths:
                if _remove_path(sanitized, path):
                    ignored_paths.append(path)
                    removed_any = True

            if not removed_any:
                raise


def _collect_extra_paths(exc: ValidationError) -> list[tuple[str | int, ...]]:
    """Return unique paths for extra-forbidden validation errors."""
    paths: set[tuple[str | int, ...]] = set()
    for error in exc.errors():
        if error.get("type") == "extra_forbidden":
            loc = tuple(error.get("loc", ()))
            if loc:
                paths.add(loc)
    return sorted(paths, key=len, reverse=True)


def _remove_path(data: dict | list, path: tuple[str | int, ...]) -> bool:
    """Remove a nested dict/list path if it exists."""
    current = data

    for part in path[:-1]:
        if isinstance(current, dict) and isinstance(part, str) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and isinstance(part, int) and 0 <= part < len(current):
            current = current[part]
            continue
        return False

    last = path[-1]
    if isinstance(current, dict) and isinstance(last, str) and last in current:
        del current[last]
        return True
    if isinstance(current, list) and isinstance(last, int) and 0 <= last < len(current):
        del current[last]
        return True
    return False
