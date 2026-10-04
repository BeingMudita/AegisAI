"""Background ingestion jobs.

Files arrive two ways:

* **upload** — sent from the dashboard; streamed to ``data/uploads/`` first.
* **inbox**  — copied straight onto the server into ``data/inbox/`` (the way to
  bring in large datasets without pushing them through a browser), then
  imported from the dashboard or the API.

Each file becomes an :class:`IngestJob` processed by a single worker thread
(one file at a time keeps memory flat), streaming through the knowledge base
pipeline while the job records live progress for the UI. A file whose content is
already indexed (same SHA-256) completes at once, pointing at the existing document.
"""

from __future__ import annotations

import queue
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import structlog

from app.config import get_settings
from app.database.enums import SourceType, TrustLevel
from app.rag.knowledge_base import IngestCancelled, KnowledgeBase, file_hash, get_knowledge_base
from app.rag.parsers import SUPPORTED_EXTENSIONS, is_supported, iter_blocks
from app.rag.schemas import InboxFile, InboxListing, IngestJob, IngestReport, IngestStage

logger = structlog.get_logger("aegisai.ingestion")
_MAX_JOBS_KEPT = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionManager:
    def __init__(self, kb: KnowledgeBase, *, inbox_dir: Path, upload_dir: Path) -> None:
        self.kb = kb
        self.inbox_dir = inbox_dir
        self.upload_dir = upload_dir
        self._jobs: OrderedDict[str, IngestJob] = OrderedDict()
        # job id → (file, delete when done, content hash if already known)
        self._paths: dict[str, tuple[Path, bool, str | None]] = {}
        self._cancelled: set[str] = set()
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    # -------------------------------------------------------------- submit
    def submit(
        self,
        path: Path,
        *,
        title: str,
        source: str,
        trust_level: TrustLevel,
        origin: str,
        delete_after: bool = False,
        filename: str | None = None,
        content_hash: str | None = None,
    ) -> IngestJob:
        job = IngestJob(
            filename=filename or path.name,
            title=title,
            source=source,
            trust_level=trust_level,
            origin=origin,
            size_bytes=path.stat().st_size,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._paths[job.id] = (path, delete_after, content_hash)
            while len(self._jobs) > _MAX_JOBS_KEPT:
                oldest = next(iter(self._jobs))
                if not self._jobs[oldest].done:
                    break
                self._jobs.pop(oldest)
        self._publish(job)
        self._queue.put(job.id)
        self._ensure_worker()
        return job

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="aegis-ingest", daemon=True)
                self._worker.start()

    # ---------------------------------------------------------------- inbox
    def list_inbox(self) -> InboxListing:
        files = []
        if self.inbox_dir.exists():
            for p in sorted(self.inbox_dir.rglob("*")):
                if p.is_file() and not p.name.startswith("."):
                    files.append(
                        InboxFile(
                            path=p.relative_to(self.inbox_dir).as_posix(),
                            size_bytes=p.stat().st_size,
                            supported=is_supported(p.name),
                        )
                    )
        return InboxListing(
            directory=str(self.inbox_dir),
            files=files,
            supported_extensions=list(SUPPORTED_EXTENSIONS),
        )

    def resolve_inbox(self, relative: str) -> Path:
        """Resolve a path inside the inbox; refuses anything that escapes it."""
        root = self.inbox_dir.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise FileNotFoundError(relative)
        return target

    def import_inbox(
        self,
        files: list[str] | None,
        *,
        source: str,
        trust_level: TrustLevel,
        source_per_file: bool = False,
    ) -> list[IngestJob]:
        names = files if files is not None else [f.path for f in self.list_inbox().files]
        jobs = []
        for name in names:
            path = self.resolve_inbox(name)
            if not is_supported(path.name):
                continue
            jobs.append(
                self.submit(
                    path,
                    title=path.name,
                    source=path.name if source_per_file else source,
                    trust_level=trust_level,
                    origin="inbox",
                )
            )
        return jobs

    # ----------------------------------------------------------------- jobs
    def list_jobs(self) -> list[IngestJob]:
        with self._lock:
            return [j.model_copy() for j in reversed(self._jobs.values())]

    def get(self, job_id: str) -> IngestJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy() if job else None

    def cancel(self, job_id: str) -> IngestJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.done:
                return job
            self._cancelled.add(job_id)
            if job.stage == IngestStage.QUEUED:
                job.stage = IngestStage.CANCELLED
                job.finished_at = _now()
            snapshot = job.model_copy()
        self._publish(snapshot)
        return snapshot

    # Hooks — the Postgres manager shares job state through ``ingest_jobs``.
    def _publish(self, job: IngestJob) -> None:
        """Called with a snapshot after every change to a job."""

    def _should_cancel(self, job_id: str) -> bool:
        return job_id in self._cancelled

    def wait(self, job_id: str, timeout: float = 30.0) -> IngestJob | None:
        """Block until a job finishes (tests and scripts)."""
        deadline = _now().timestamp() + timeout
        while _now().timestamp() < deadline:
            job = self.get(job_id)
            if job is None or job.done:
                return job
            threading.Event().wait(0.02)
        return self.get(job_id)

    # --------------------------------------------------------------- worker
    def _run(self) -> None:
        while True:
            try:
                job_id = self._queue.get(timeout=5)
            except queue.Empty:
                return  # idle: the thread exits and is restarted on the next submit
            try:
                self._process(job_id)
            finally:
                self._queue.task_done()

    def _process(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            path, delete_after, content_hash = self._paths.pop(job_id, (None, False, None))
            if job is None or path is None or job.stage == IngestStage.CANCELLED:
                return
            job.stage = IngestStage.PARSING
            job.started_at = _now()

        def progress(stage: IngestStage, bytes_done: int, report: IngestReport) -> None:
            with self._lock:
                job.stage = stage
                job.bytes_read = max(job.bytes_read, bytes_done)
                job.chunks_total = report.chunks_total
                job.chunks_indexed = report.chunks_indexed
                job.chunks_flagged = report.chunks_flagged
                job.chunks_quarantined = report.chunks_quarantined
                snapshot = job.model_copy()
            self._publish(snapshot)

        try:
            content_hash = content_hash or file_hash(path)
            if existing := self.kb.find_by_hash(content_hash):
                with self._lock:
                    job.stage = IngestStage.COMPLETED
                    job.duplicate_of = job.document_id = existing.document_id
                    job.bytes_read = job.size_bytes
                return  # the finally block publishes the job and removes an upload
            report = self.kb.ingest_stream(
                iter_blocks(path),
                title=job.title,
                source=job.source,
                trust_level=job.trust_level,
                source_type=SourceType.FILE,
                filename=job.filename,
                size_bytes=job.size_bytes,
                content_hash=content_hash,
                progress=progress,
                should_cancel=lambda: self._should_cancel(job_id),
            )
            self.kb.save()
            with self._lock:
                job.stage = IngestStage.COMPLETED
                job.document_id = report.document_id
                job.bytes_read = job.size_bytes
                job.chunks_total = report.chunks_total
                job.chunks_indexed = report.chunks_indexed
                job.chunks_flagged = report.chunks_flagged
                job.chunks_quarantined = report.chunks_quarantined
        except IngestCancelled:
            with self._lock:
                job.stage = IngestStage.CANCELLED
        except Exception as exc:  # noqa: BLE001 — any parse/ingest failure is reported on the job
            logger.warning("ingest_failed", file=job.filename, error=str(exc))
            with self._lock:
                job.stage = IngestStage.FAILED
                job.error = str(exc)
        finally:
            with self._lock:
                job.finished_at = _now()
                self._cancelled.discard(job_id)
                snapshot = job.model_copy()
            self._publish(snapshot)
            if delete_after:
                path.unlink(missing_ok=True)


@lru_cache
def get_ingestion_manager() -> IngestionManager:
    settings = get_settings()
    kwargs = {
        "inbox_dir": settings.data_path("inbox"),
        "upload_dir": settings.data_path("uploads"),
    }
    if settings.use_postgres:
        from app.persistence.jobs import PostgresIngestionManager

        return PostgresIngestionManager(get_knowledge_base(), **kwargs)
    return IngestionManager(get_knowledge_base(), **kwargs)
