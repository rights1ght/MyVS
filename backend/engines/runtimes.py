from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENVS = ROOT / ".venvs"

# Heavy adapters with mutually incompatible pins get isolated environments.
ADAPTER_ENV = {
    "chatterbox": "chatterbox",
    "chatterbox_turbo": "chatterbox",
    "omnivoice": "omnivoice",
    "voxcpm2": "voxcpm",
    "gigaam": "gigaam",
}


def venv_python(name: str) -> Path:
    return VENVS / name / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def python_for(adapter: str) -> tuple[str, str]:
    """Return interpreter and a human-readable runtime label."""
    env_name = ADAPTER_ENV.get(adapter)
    if env_name:
        candidate = venv_python(env_name)
        if candidate.exists():
            return str(candidate), str(candidate)
        return sys.executable, f"main fallback (нет .venvs/{env_name})"
    return sys.executable, "main"


def runtime_status() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for adapter, env_name in ADAPTER_ENV.items():
        candidate = venv_python(env_name)
        result[adapter] = {
            "env": env_name,
            "installed": candidate.exists(),
            "python": str(candidate) if candidate.exists() else "",
            "fallback": not candidate.exists(),
        }
    return result
