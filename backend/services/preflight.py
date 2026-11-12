"""Start-up self-check: tell the user *what* is missing and *how* to fix it.

Typical failure on a fresh machine: the server starts (FastAPI is installed) but the model
packages are not - downloads and model loading then fail one by one with
``ModuleNotFoundError`` deep inside a worker, and a CPU-only PyTorch silently keeps models off the GPU.
"""
from __future__ import annotations

import importlib.metadata
import re
import sys
from pathlib import Path
from typing import Any, Callable

from backend.config import ROOT_DIR

_REQ_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def read_requirements(path: Path | None = None) -> dict[str, str]:
    """name -> pinned version ('' when not pinned) from requirements.txt (option lines are skipped)."""
    path = path or ROOT_DIR / "requirements.txt"
    if not path.exists():
        return {}
    wanted: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _REQ_NAME.match(line)
        if match:
            pinned = re.search(r"==\s*([^\s;,]+)", line)
            wanted[match.group(1)] = pinned.group(1) if pinned else ""
    return wanted


def _installed(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def check_environment(
    *,
    requirements: dict[str, str] | None = None,
    gpu_present: bool = False,
    platform: str | None = None,
    version_of: Callable[[str], str | None] = _installed,
    python: str | None = None,
) -> list[dict[str, Any]]:
    """Problems that will break or slow MyVS, each ``{"code", "message"}``. Empty list = all good."""
    requirements = read_requirements() if requirements is None else requirements
    platform = platform or sys.platform
    python = python or sys.executable
    problems: list[dict[str, Any]] = []

    missing = sorted(name for name in requirements if version_of(name) is None)
    if missing:
        problems.append({
            "code": "MISSING_PACKAGES",
            "packages": missing,
            "message": (
                f"Не установлены пакеты из requirements.txt: {', '.join(missing)}. Скачивание и загрузка моделей "
                f'будут падать. Python, которым запущен MyVS: {python}. Установите: "{python}" -m pip install -r requirements.txt'
            ),
        })

    torch = version_of("torch")
    if torch and gpu_present:
        cuda_build = "+cu" in torch
        # PyPI's Windows wheel is CPU-only without any tag; on Linux the untagged wheel is the CUDA build.
        cpu_only = "+cpu" in torch or (platform.startswith("win") and "+" not in torch)
        if cpu_only and not cuda_build:
            pins = " ".join(f"{name}=={requirements[name]}" for name in ("torch", "torchaudio") if requirements.get(name)) or "torch torchaudio"
            problems.append({
                "code": "TORCH_WITHOUT_CUDA",
                "message": (
                    f"Найдена видеокарта NVIDIA, но установлен PyTorch без CUDA ({torch}): модели будут работать на CPU. "
                    f'Установите CUDA-сборку: "{python}" -m pip install --force-reinstall {pins} '
                    "--index-url https://download.pytorch.org/whl/cu128"
                ),
            })
    return problems
