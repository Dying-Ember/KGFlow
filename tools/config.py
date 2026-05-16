"""Load kgflow.toml project configuration."""

import tomllib
from pathlib import Path
from typing import Optional


def load_kgflow_config(kgflow_root: Path) -> Optional[dict]:
    """Load kgflow.toml from the KGFlow project root.

    Returns the full parsed TOML dict, or None if the file is absent.
    """
    config_path = kgflow_root / "kgflow.toml"
    if not config_path.exists():
        return None
    with open(config_path, "rb") as f:
        return tomllib.load(f)
