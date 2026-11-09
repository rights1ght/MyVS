from __future__ import annotations

import time

from backend.db.session import init_db
from backend.services.model_registry import registry
from backend.services.resource_manager import resources


def main() -> None:
    init_db()
    registry.sync()
    variant = registry.get_variant("faster-whisper-tiny", "int8")
    print("variant", variant.id, variant.install_state, variant.install_path)
    plan = resources.plan("faster-whisper-tiny", "int8")
    print("plan", plan.verdict, plan.need_vram_gb, plan.free_vram_gb)
    runtime = resources.ensure_loaded("faster-whisper-tiny", "int8")
    print("loaded", runtime.public())
    print("status", resources.status()["memory"])
    time.sleep(1)
    print(resources.unload("faster-whisper-tiny"))


if __name__ == "__main__":
    main()
