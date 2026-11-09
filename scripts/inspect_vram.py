from __future__ import annotations

import subprocess
import time

from backend.db.session import init_db
from backend.services.model_registry import registry
from backend.services.resource_manager import resources


def main() -> None:
    init_db()
    registry.sync()
    runtime = resources.ensure_loaded("faster-whisper-tiny", "int8")
    print("runtime", runtime.public())
    print("worker pid", runtime.worker.pid)
    print(subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout)
    print(subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader"], capture_output=True, text=True).stdout)
    time.sleep(2)
    resources.unload("faster-whisper-tiny")
    time.sleep(3)
    print("after", subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader"], capture_output=True, text=True).stdout)


if __name__ == "__main__":
    main()
