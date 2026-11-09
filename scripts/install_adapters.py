#!/usr/bin/env python3
"""Create isolated environments for heavy/conflicting TTS-STT adapters."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENVS = ROOT / ".venvs"

ADAPTERS = {
    "omnivoice": {"package": "omnivoice"},
    "gigaam": {"package": "gigaam"},
    "chatterbox": {"package": "chatterbox-tts"},
    "voxcpm": {"package": "voxcpm"},
}


def python_for(env: str) -> Path:
    return VENVS / env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(cwd or ROOT))


def install(env: str) -> None:
    spec = ADAPTERS[env]
    target = VENVS / env
    if not python_for(env).exists():
        run([sys.executable, "-m", "venv", "--system-site-packages", str(target)])
    python = str(python_for(env))
    run([python, "-m", "pip", "install", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", spec["package"]])
    # Heavy CUDA torch lives in the main .venv; drop the CPU copy installed by
    # the adapter so the worker's main-site fallback uses the CUDA build.
    run([python, "-m", "pip", "uninstall", "-y", "torch", "torchaudio"])
    print(f"[ok] {env}: {python}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("adapters", nargs="*", choices=sorted(ADAPTERS) + [], help="adapter names")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    names = sorted(ADAPTERS) if args.all or not args.adapters else args.adapters
    for name in names:
        if name not in ADAPTERS:
            print(f"unknown adapter: {name}", file=sys.stderr)
            return 2
        install(name)
    print("Done. Restart MyVS to pick up new runtimes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
