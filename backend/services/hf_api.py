"""Minimal Hugging Face Hub file listing over plain HTTPS.

The downloader only needs "which files does this repo revision contain, how big, which SHA-256".
Doing that with ``httpx`` (already a hard dependency) removes the need for ``huggingface_hub`` -
a missing package made every model download fail - and honours ``HF_ENDPOINT`` like the official
client, so a mirror can be used where huggingface.co is blocked.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote

import httpx

DEFAULT_ENDPOINT = "https://huggingface.co"


class HubError(RuntimeError):
    pass


def hf_endpoint() -> str:
    return (os.environ.get("HF_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")


def resolve_url(repo: str, revision: str, path: str) -> str:
    return f"{hf_endpoint()}/{repo}/resolve/{quote(revision, safe='')}/{quote(path, safe='/')}"


def _next_page(response: httpx.Response) -> str | None:
    match = re.search(r'<([^>]+)>;\s*rel="next"', response.headers.get("link", ""))
    return match.group(1) if match else None


def list_repo_files(repo: str, revision: str = "main", token: str | None = None) -> list[dict[str, Any]]:
    """Files of ``repo`` at ``revision``: ``[{"path", "size", "sha256"}]`` (sha256 only for LFS files)."""
    url: str | None = f"{hf_endpoint()}/api/models/{repo}/tree/{quote(revision, safe='')}?recursive=true"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    files: list[dict[str, Any]] = []
    try:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0), headers=headers) as client:
            for _page in range(50):  # the API pages at ~1000 entries; 50 pages is far beyond any model repo
                response = client.get(url)
                if response.status_code in (401, 403):
                    raise HubError(f"Репозиторий {repo} закрыт или требует токен (задайте переменную HF_TOKEN).")
                if response.status_code == 404:
                    raise HubError(f"Репозиторий или ревизия не найдены: {repo}@{revision}.")
                response.raise_for_status()
                for entry in response.json():
                    if entry.get("type") != "file":
                        continue
                    lfs = entry.get("lfs") or {}
                    files.append({
                        "path": str(entry["path"]),
                        "size": int(lfs.get("size") or entry.get("size") or 0),
                        "sha256": str(lfs.get("oid") or ""),
                    })
                url = _next_page(response)
                if not url:
                    break
    except httpx.HTTPError as exc:
        raise HubError(
            f"Не удалось получить список файлов {repo}: {exc}. Проверьте доступ к {hf_endpoint()} "
            "(при блокировке задайте зеркало через переменную HF_ENDPOINT)."
        ) from exc
    return files
