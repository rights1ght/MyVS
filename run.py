#!/usr/bin/env python3
"""One-command launcher for MyVS (Windows / Linux)."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
FRONTEND = ROOT / "frontend"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def in_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == venv_python().resolve()
    except OSError:
        return False


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd or ROOT), check=True)


def bootstrap_venv() -> None:
    if in_venv():
        return
    if venv_python().exists():
        print(f"Перезапуск в venv: {venv_python()}", flush=True)
        os.execv(str(venv_python()), [str(venv_python()), str(Path(__file__).resolve()), *sys.argv[1:]])
    print("Создаю .venv ...", flush=True)
    run([sys.executable, "-m", "venv", str(VENV)])
    python = str(venv_python())
    run([python, "-m", "pip", "install", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    print("Зависимости установлены; перезапуск в venv.", flush=True)
    os.execv(python, [python, str(Path(__file__).resolve()), *sys.argv[1:]])


def npm_command() -> str:
    if os.name == "nt":
        candidate = shutil.which("npm.cmd")
        if candidate:
            return candidate
    candidate = shutil.which("npm")
    if not candidate:
        raise RuntimeError("npm не найден. Установите Node.js 20+.")
    return candidate


def frontend_needs_build() -> bool:
    index = FRONTEND / "dist" / "index.html"
    if not index.exists():
        return True
    newest = 0.0
    for path in (FRONTEND / "src").rglob("*"):
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    for name in ("package.json", "vite.config.ts", "tailwind.config.js", "index.html"):
        path = FRONTEND / name
        if path.exists():
            newest = max(newest, path.stat().st_mtime)
    return newest > index.stat().st_mtime


def ensure_frontend(rebuild: bool = False) -> int:
    if not FRONTEND.exists():
        raise RuntimeError("Каталог frontend не найден.")
    npm = npm_command()
    node_modules = FRONTEND / "node_modules"
    started = time.perf_counter()
    if not node_modules.exists():
        run([npm, "install"], cwd=FRONTEND)
    if rebuild or frontend_needs_build():
        run([npm, "run", "build"], cwd=FRONTEND)
    return int((time.perf_counter() - started) * 1000)


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def open_browser(url: str) -> None:
    time.sleep(1.6)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="MyVS local speech studio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dev", action="store_true", help="force frontend rebuild + backend reload")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--rebuild", action="store_true", help="force frontend rebuild")
    parser.add_argument("--skip-install", action="store_true", help="do not create venv/install deps")
    args = parser.parse_args()

    if not args.skip_install:
        bootstrap_venv()

    if not port_free(args.host, args.port):
        print(f"Порт {args.port} занят. Укажите --port.", file=sys.stderr)
        return 2

    os.environ["MYVS_STARTED_AT"] = str(time.time())
    os.environ["MYVS_HOST"] = args.host
    os.environ["MYVS_PORT"] = str(args.port)

    build_ms = ensure_frontend(rebuild=args.rebuild or args.dev)
    os.environ["MYVS_FRONTEND_BUILD_MS"] = str(build_ms)
    print(f"Frontend готов за {build_ms} ms", flush=True)
    if args.dev:
        print("Dev-режим: backend reload; frontend пересобран и отдаётся статически.", flush=True)

    url = f"http://{args.host}:{args.port}"
    print(f"\nMyVS: {url}\nДокументация API: {url}/docs\n", flush=True)
    if not args.no_browser and os.environ.get("MYVS_AUTO_BROWSER", "1") != "0":
        import threading

        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.dev,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
