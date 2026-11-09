from __future__ import annotations

import base64
import json
import os
from multiprocessing.connection import Client

from backend.engines.worker_main import worker_entry


def main() -> None:
    host = os.environ["MYVS_WORKER_HOST"]
    port = int(os.environ["MYVS_WORKER_PORT"])
    authkey = bytes.fromhex(os.environ["MYVS_WORKER_AUTH"])
    spec = json.loads(base64.b64decode(os.environ["MYVS_SPEC"]).decode("utf-8"))
    conn = Client((host, port), authkey=authkey)
    worker_entry(conn, spec)


if __name__ == "__main__":
    main()
