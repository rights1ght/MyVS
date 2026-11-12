from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from sqlmodel import Session, select

from backend.config import settings
from backend.db.models import Download, ModelVariant
from backend.db.session import session_scope
from backend.services.model_registry import package_available, registry

logger = logging.getLogger(__name__)

HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _lfs_sha(sibling: Any) -> str:
    lfs = getattr(sibling, "lfs", None)
    if isinstance(lfs, dict):
        return str(lfs.get("sha256") or "")
    return str(getattr(lfs, "sha256", "") or "") if lfs else ""


@dataclass
class DownloadJob:
    download_id: str
    stop: threading.Event = field(default_factory=threading.Event)
    pause: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class DownloadError(Exception):
    pass


class DownloadManager:
    def __init__(self) -> None:
        self.jobs: dict[str, DownloadJob] = {}
        self.by_variant: dict[str, str] = {}
        self._lock = threading.Lock()

    def active_for_variant(self, variant_id: str) -> Download | None:
        download_id = self.by_variant.get(variant_id)
        if not download_id:
            return None
        with session_scope() as session:
            return session.get(Download, download_id)

    def start(self, model_id: str, variant_id: str, *, resume: bool = False) -> Download:
        variant = registry.get_variant(model_id, variant_id)
        if not variant:
            raise DownloadError("Вариант модели не найден.")
        download_spec = dict(variant.source or {})
        if download_spec.get("type") in (None, "local"):
            raise DownloadError("Для этого варианта не настроен источник скачивания.")
        with self._lock:
            existing = self.by_variant.get(variant.id)
            if existing and existing in self.jobs and self.jobs[existing].thread and self.jobs[existing].thread.is_alive():
                with session_scope() as session:
                    row = session.get(Download, existing)
                    if row:
                        return row
            with session_scope() as session:
                row = Download(
                    model_id=model_id,
                    variant_id=variant.id,
                    status="downloading" if resume else "queued",
                    resumable=True,
                    dest_path=variant.install_path,
                )
                session.add(row)
                session.flush()
                session.refresh(row)
                download_id = row.id
                session.commit()
            job = DownloadJob(download_id=download_id)
            self.jobs[download_id] = job
            self.by_variant[variant.id] = download_id
            job.thread = threading.Thread(
                target=self._run,
                args=(job, model_id, variant.id, download_spec),
                name=f"download-{model_id}-{variant.id}",
                daemon=True,
            )
            job.thread.start()
            with session_scope() as session:
                return session.get(Download, download_id)  # type: ignore[return-value]

    def pause(self, download_id: str) -> Download | None:
        job = self.jobs.get(download_id)
        if job:
            job.pause.set()
        with session_scope() as session:
            row = session.get(Download, download_id)
            if row and row.status in ("downloading", "queued"):
                row.status = "paused"
                row.updated_at = _utcnow()
                session.add(row)
            return row

    def resume(self, download_id: str) -> Download | None:
        with session_scope() as session:
            row = session.get(Download, download_id)
            if not row:
                return None
            model_id, variant_id = row.model_id, row.variant_id
        self.jobs.pop(download_id, None)
        self.by_variant.pop(variant_id, None)
        return self.start(model_id, variant_id, resume=True)

    def cancel(self, download_id: str) -> Download | None:
        job = self.jobs.get(download_id)
        if job:
            job.stop.set()
        with session_scope() as session:
            row = session.get(Download, download_id)
            if row:
                row.status = "cancelled"
                row.updated_at = _utcnow()
                session.add(row)
            return row

    def get(self, download_id: str) -> Download | None:
        with session_scope() as session:
            return session.get(Download, download_id)

    def list(self) -> list[Download]:
        with session_scope() as session:
            rows = list(session.exec(select(Download).order_by(Download.created_at.desc()).limit(100)).all())
        latest: dict[str, Download] = {}
        for row in rows:
            latest.setdefault(row.variant_id, row)
        return list(latest.values())[:50]

    def mark_interrupted(self) -> None:
        """A previous server process did not finish its downloads."""
        with session_scope() as session:
            rows = session.exec(select(Download).where(Download.status.in_(["queued", "downloading", "verifying"]))).all()
            for row in rows:
                row.status = "paused"
                row.error = "Загрузка прервана перезапуском; можно продолжить."
                row.updated_at = _utcnow()
                session.add(row)
        with session_scope() as session:
            variants = session.exec(select(ModelVariant).where(ModelVariant.install_state == "downloading")).all()
            for variant in variants:
                variant.install_state = "paused"
                variant.updated_at = _utcnow()
                session.add(variant)

    def _update(self, download_id: str, **fields: Any) -> None:
        with session_scope() as session:
            row = session.get(Download, download_id)
            if not row:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = _utcnow()
            # Only reset the speed when the caller did not report one and the job is no longer running;
            # resetting it unconditionally made the UI show 0 B/s for every download.
            if "speed_bps" not in fields and row.status in ("completed", "paused", "cancelled", "error"):
                row.speed_bps = 0.0
            session.add(row)

    def _variant_update(self, variant_id: str, **fields: Any) -> None:
        with session_scope() as session:
            variant = session.get(ModelVariant, variant_id)
            if not variant:
                return
            for key, value in fields.items():
                setattr(variant, key, value)
            variant.updated_at = _utcnow()
            session.add(variant)

    def _manifest(self, model_id: str, variant: ModelVariant, spec: dict[str, Any]) -> tuple[list[dict[str, Any]], Path]:
        kind = str(spec.get("type") or "")
        dest = Path(variant.install_path or settings.data_dir / "models" / model_id / variant.id.split(":")[-1])
        dest.mkdir(parents=True, exist_ok=True)
        if kind == "package":
            return [], dest
        if kind == "url_files":
            files = []
            for entry in spec.get("files") or []:
                files.append(
                    {
                        "path": entry["path"],
                        "url": entry["url"],
                        "size": int(entry.get("size") or 0),
                        "sha256": str(entry.get("sha256") or ""),
                    }
                )
            return files, dest
        if kind not in ("hf", "hf_files"):
            raise DownloadError(f"Неизвестный тип загрузки: {kind}")
        from huggingface_hub import HfApi

        repo = str(spec.get("repo") or "")
        revision = str(spec.get("revision") or "main")
        if not repo:
            raise DownloadError("В источнике не указан HF-репозиторий.")
        info = HfApi(token=HF_TOKEN).model_info(repo, revision=revision, files_metadata=True)
        include = list(spec.get("include") or [])
        files: list[dict[str, Any]] = []
        for sibling in info.siblings or []:
            name = sibling.rfilename
            if name in (".gitattributes", "README.md"):
                continue
            if include and not any(fnmatch.fnmatch(name, pattern) for pattern in include):
                continue
            files.append(
                {
                    "path": name,
                    "url": f"https://huggingface.co/{repo}/resolve/{revision}/{quote(name, safe='/')}",
                    "size": int(getattr(sibling, "size", 0) or 0),
                    "sha256": _lfs_sha(sibling),
                }
            )
        if not files:
            raise DownloadError("HF-репозиторий не содержит подходящих файлов.")
        return files, dest

    def _run(self, job: DownloadJob, model_id: str, variant_id: str, spec: dict[str, Any]) -> None:
        started = time.monotonic()
        try:
            with session_scope() as session:
                variant = session.get(ModelVariant, variant_id)
            if not variant:
                raise DownloadError("Вариант модели не найден.")
            self._update(job.download_id, status="downloading", error="")
            self._variant_update(variant_id, install_state="downloading")
            files, dest = self._manifest(model_id, variant, spec)
            if spec.get("type") == "package":
                package = str(spec.get("package") or "")
                if package and package_available(package):
                    self._variant_update(variant_id, install_state="installed", install_path="")
                    self._update(job.download_id, status="completed", bytes_total=0, bytes_done=0)
                else:
                    raise DownloadError(f"Python-пакет {package} не установлен.")
                return
            total = sum(int(item["size"]) for item in files)
            self._update(job.download_id, bytes_total=total)
            completed = 0
            last_update = 0.0
            last_bytes = 0
            for item in files:
                if job.stop.is_set():
                    self._update(job.download_id, status="cancelled", bytes_done=completed)
                    self._variant_update(variant_id, install_state="not_installed")
                    return
                if job.pause.is_set():
                    self._update(job.download_id, status="paused", bytes_done=completed)
                    self._variant_update(variant_id, install_state="paused")
                    return
                target = dest / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                expected = int(item.get("size") or 0)
                if target.exists() and (not expected or target.stat().st_size == expected):
                    completed += target.stat().st_size
                    self._update(job.download_id, bytes_done=min(completed, total))
                    continue
                part = target.with_name(target.name + ".part")
                if expected and part.exists() and part.stat().st_size > expected:
                    part.unlink(missing_ok=True)
                base_done = completed
                downloaded = 0
                offset = 0
                hasher = hashlib.sha256()
                last_error: Exception | None = None
                for attempt in range(5):
                    if job.stop.is_set() or job.pause.is_set():
                        break
                    offset = part.stat().st_size if part.exists() else 0
                    if expected and offset == expected:
                        # Whole file already on disk (e.g. crash before the final rename): it still has to be
                        # hashed, otherwise the empty hasher below fails the checksum comparison.
                        if item.get("sha256"):
                            hasher = hashlib.sha256()
                            with part.open("rb") as handle:
                                for block in iter(lambda: handle.read(1024 * 1024), b""):
                                    hasher.update(block)
                        last_error = None
                        break
                    downloaded = 0
                    hasher = hashlib.sha256()
                    if offset and item.get("sha256"):
                        with part.open("rb") as handle:
                            for block in iter(lambda: handle.read(1024 * 1024), b""):
                                hasher.update(block)
                    headers = {}
                    if HF_TOKEN and "huggingface.co" in item["url"]:
                        headers["Authorization"] = f"Bearer {HF_TOKEN}"
                    if offset:
                        headers["Range"] = f"bytes={offset}-"
                    try:
                        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=120.0)) as client:
                            with client.stream("GET", item["url"], headers=headers) as response:
                                if offset and response.status_code == 200:
                                    part.unlink(missing_ok=True)
                                    offset = 0
                                    hasher = hashlib.sha256()
                                elif response.status_code not in (200, 206):
                                    raise DownloadError(f"HTTP {response.status_code} для {item['path']}")
                                mode = "ab" if offset and response.status_code == 206 else "wb"
                                with part.open(mode) as handle:
                                    for chunk in response.iter_bytes(1024 * 1024):
                                        if job.stop.is_set() or job.pause.is_set():
                                            break
                                        handle.write(chunk)
                                        hasher.update(chunk)
                                        downloaded += len(chunk)
                                        now = time.monotonic()
                                        if now - last_update > 0.5:
                                            speed = (base_done + offset + downloaded - last_bytes) / max(now - last_update, 0.001)
                                            self._update(
                                                job.download_id,
                                                bytes_done=min(total, base_done + offset + downloaded),
                                                speed_bps=round(max(0.0, speed), 1),
                                            )
                                            last_update = now
                                            last_bytes = base_done + offset + downloaded
                        last_error = None
                    except Exception as exc:
                        last_error = exc
                        logger.warning("download attempt %s/%s failed for %s: %s", attempt + 1, 5, item["path"], exc)
                        if attempt < 4:
                            time.sleep(min(2 ** attempt, 8))
                            continue
                        break
                    actual_now = part.stat().st_size if part.exists() else 0
                    if expected and actual_now < expected:
                        last_error = DownloadError(f"Получено {actual_now} из {expected} байт")
                        if attempt < 4:
                            time.sleep(min(2 ** attempt, 8))
                            continue
                    break
                if job.stop.is_set():
                    self._update(job.download_id, status="cancelled", bytes_done=min(base_done + offset + downloaded, total))
                    self._variant_update(variant_id, install_state="not_installed")
                    return
                if job.pause.is_set():
                    self._update(job.download_id, status="paused", bytes_done=min(base_done + offset + downloaded, total))
                    self._variant_update(variant_id, install_state="paused")
                    return
                if last_error is not None:
                    raise DownloadError(f"Загрузка {item['path']} не завершилась: {last_error}")
                actual = part.stat().st_size
                if expected and actual != expected:
                    raise DownloadError(f"Размер {item['path']} не совпадает: {actual} != {expected}")
                if item.get("sha256"):
                    digest = hasher.hexdigest()
                    if digest.lower() != str(item["sha256"]).lower():
                        raise DownloadError(f"Контрольная сумма не совпала: {item['path']}")
                part.replace(target)
                completed = base_done + actual
                self._update(job.download_id, bytes_done=min(completed, total), speed_bps=0.0)
            marker = {
                "model_id": model_id,
                "variant_id": variant_id,
                "repo": spec.get("repo", ""),
                "revision": spec.get("revision", ""),
                "files": [{"path": item["path"], "size": item.get("size", 0), "sha256": item.get("sha256", "")} for item in files],
                "completed_at": _utcnow().isoformat(),
                "elapsed_sec": round(time.monotonic() - started, 1),
            }
            (dest / ".myvs-complete").write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            self._variant_update(
                variant_id,
                install_state="installed",
                install_path=str(dest),
                installed_bytes=completed,
                sha256=marker.get("revision", ""),
            )
            self._update(job.download_id, status="completed", bytes_done=completed, speed_bps=0.0, error="")
            logger.info("download complete: %s / %s (%d bytes)", model_id, variant_id, completed)
        except Exception as exc:
            logger.exception("download failed: %s / %s", model_id, variant_id)
            self._variant_update(variant_id, install_state="error")
            self._update(job.download_id, status="error", error=str(exc), speed_bps=0.0)
        finally:
            with self._lock:
                current = self.jobs.get(job.download_id)
                if current is job:
                    self.jobs.pop(job.download_id, None)
                if self.by_variant.get(variant_id) == job.download_id:
                    self.by_variant.pop(variant_id, None)

    def verify(self, model_id: str, variant_id: str) -> dict[str, Any]:
        variant = registry.get_variant(model_id, variant_id)
        if not variant:
            raise DownloadError("Вариант не найден.")
        spec = dict(variant.source or {})
        if spec.get("type") == "package":
            package = str(spec.get("package") or "")
            ok = bool(package and package_available(package))
            state = "installed" if ok else "error"
            self._variant_update(variant.id, install_state=state)
            return {"ok": ok, "level": "package", "message": "Пакет установлен" if ok else "Пакет не установлен"}
        if spec.get("type") == "local":
            path = Path(variant.install_path or "")
            return {"ok": path.exists(), "level": "path", "message": str(path)}
        files, dest = self._manifest(model_id, variant, spec)
        missing: list[str] = []
        bad: list[str] = []
        hashed = 0
        for item in files:
            path = dest / item["path"]
            if not path.exists():
                missing.append(item["path"])
                continue
            if item.get("size") and path.stat().st_size != int(item["size"]):
                bad.append(item["path"])
                continue
            expected_hash = str(item.get("sha256") or "")
            if expected_hash:
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest().lower() != expected_hash.lower():
                    bad.append(item["path"])
                else:
                    hashed += 1
        ok = not missing and not bad
        state = "installed" if ok else "error"
        if ok:
            (dest / ".myvs-complete").write_text(
                json.dumps({"verified_at": _utcnow().isoformat(), "files": len(files)}, ensure_ascii=False),
                encoding="utf-8",
            )
        self._variant_update(variant.id, install_state=state)
        return {
            "ok": ok,
            "level": f"sha256({hashed}/{len(files)})+size" if hashed else "size",
            "missing": missing,
            "bad": bad,
            "files": len(files),
            "message": "Целостность подтверждена" if ok else "Есть отсутствующие или повреждённые файлы",
        }


downloads = DownloadManager()
