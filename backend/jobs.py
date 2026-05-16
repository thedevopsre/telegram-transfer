from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    MessageIdInvalidError,
    RPCError,
)

import db
from models import DryRunResponse, JobDetailResponse, JobItemError, JobStatus, MessageItemStatus
from telegram_client import telegram_service

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_PATH = DATA_DIR / "transfer.log"
logger = logging.getLogger(__name__)


def setup_transfer_logger() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(LOG_PATH) for h in logger.handlers):
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)


class JobRunner:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._pause_events: dict[str, asyncio.Event] = {}
        self._cancel_flags: dict[str, bool] = {}

    def _pause_event(self, job_id: str) -> asyncio.Event:
        if job_id not in self._pause_events:
            self._pause_events[job_id] = asyncio.Event()
            self._pause_events[job_id].set()
        return self._pause_events[job_id]

    async def dry_run(self, target_chat_id: int, message_ids: list[int]) -> DryRunResponse:
        setup_transfer_logger()
        writable, title, err = await telegram_service.validate_target_writable(target_chat_id)
        if not writable:
            return DryRunResponse(0, 0, [], title, False, [err])
        invalid, valid = [], []
        for mid in sorted(set(message_ids)):
            client = await telegram_service.ensure_connected()
            msg = await client.get_messages("me", ids=mid)
            if msg is None or (isinstance(msg, list) and not msg[0]):
                invalid.append(mid)
            else:
                valid.append(mid)
        job_id = db.create_job(target_chat_id, valid, target_title=title, dry_run=True)
        db.update_job_status(job_id, JobStatus.COMPLETED)
        warnings = [f"{len(invalid)} message(s) not found."] if invalid else []
        return DryRunResponse(len(valid), 0, invalid, title, True, warnings)

    async def start_job(self, target_chat_id: int, message_ids: list[int], **kwargs) -> str:
        setup_transfer_logger()
        writable, title, err = await telegram_service.validate_target_writable(target_chat_id)
        if not writable:
            raise ValueError(err)
        job_id = db.create_job(target_chat_id, sorted(set(message_ids)), target_title=title, **kwargs)
        self._cancel_flags[job_id] = False
        self._pause_event(job_id).set()
        if job_id not in self._tasks or self._tasks[job_id].done():
            self._tasks[job_id] = asyncio.create_task(self._run_job(job_id))
        return job_id

    async def _run_job(self, job_id: str) -> None:
        job = db.get_job(job_id)
        if not job:
            return
        db.update_job_status(job_id, JobStatus.RUNNING)
        target = job["target_chat_id"]
        batch_size = job["batch_size"]
        delay = job["batch_delay_seconds"]
        copy_mode = bool(job["copy_instead_of_forward"])
        silent = bool(job["silent"])
        try:
            while True:
                if self._cancel_flags.get(job_id):
                    db.update_job_status(job_id, JobStatus.CANCELLED)
                    return
                await self._pause_event(job_id).wait()
                pending = db.get_pending_message_ids(job_id)
                if not pending:
                    db.update_job_status(job_id, JobStatus.COMPLETED)
                    return
                batch = pending[:batch_size]
                try:
                    results = await telegram_service.forward_batch(
                        target, batch, copy_instead_of_forward=copy_mode, silent=silent
                    )
                    for src, tgt in results.items():
                        if db.is_message_sent(job_id, src):
                            continue
                        if tgt is not None:
                            db.update_job_item(job_id, src, MessageItemStatus.SENT, target_message_id=tgt)
                        else:
                            db.update_job_item(job_id, src, MessageItemStatus.FAILED, reason="No target ID")
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 1)
                    continue
                except ChatWriteForbiddenError:
                    db.update_job_status(job_id, JobStatus.FAILED, error_message="Cannot write to target.")
                    return
                except MessageIdInvalidError:
                    for mid in batch:
                        db.update_job_item(job_id, mid, MessageItemStatus.SKIPPED, reason="Invalid/deleted")
                except RPCError as e:
                    for mid in batch:
                        if not db.is_message_sent(job_id, mid):
                            reason = "Protected content" if "RESTRICTED" in str(e) else str(e)[:500]
                            db.update_job_item(job_id, mid, MessageItemStatus.FAILED, reason=reason)
                except Exception as e:
                    for mid in batch:
                        db.update_job_item(job_id, mid, MessageItemStatus.FAILED, reason=str(e)[:500])
                await asyncio.sleep(delay)
        except Exception as e:
            db.update_job_status(job_id, JobStatus.FAILED, error_message=str(e)[:500])

    def pause(self, job_id: str) -> bool:
        if not db.get_job(job_id):
            return False
        self._pause_event(job_id).clear()
        db.update_job_status(job_id, JobStatus.PAUSED)
        return True

    def resume(self, job_id: str) -> bool:
        if not db.get_job(job_id):
            return False
        self._pause_event(job_id).set()
        db.update_job_status(job_id, JobStatus.RUNNING)
        if job_id not in self._tasks or self._tasks[job_id].done():
            self._tasks[job_id] = asyncio.create_task(self._run_job(job_id))
        return True

    def cancel(self, job_id: str) -> bool:
        if not db.get_job(job_id):
            return False
        self._cancel_flags[job_id] = True
        self._pause_event(job_id).set()
        db.update_job_status(job_id, JobStatus.CANCELLED)
        return True

    def cancel_all(self) -> None:
        for job_id in list(self._tasks.keys()):
            self.cancel(job_id)

    async def resume_incomplete_on_startup(self) -> None:
        setup_transfer_logger()
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE status IN (?, ?) AND dry_run = 0",
                (JobStatus.RUNNING.value, JobStatus.PAUSED.value),
            ).fetchall()
        for row in rows:
            jid = row["id"]
            db.update_job_status(jid, JobStatus.PENDING)
            self._cancel_flags[jid] = False
            self._pause_event(jid).set()
            if jid not in self._tasks or self._tasks[jid].done():
                self._tasks[jid] = asyncio.create_task(self._run_job(jid))

    def build_job_detail(self, job_id: str) -> JobDetailResponse | None:
        job = db.get_job(job_id)
        if not job:
            return None
        counts = db.get_job_counts(job_id)
        errors_raw, _ = db.get_job_errors(job_id, limit=20)
        recent = [
            JobItemError(
                source_message_id=e["source_message_id"],
                status=MessageItemStatus(e["status"]),
                reason=e["reason"] or "",
                target_message_id=e["target_message_id"],
            )
            for e in errors_raw
        ]
        return JobDetailResponse(
            job_id=job_id,
            status=JobStatus(job["status"]),
            total=counts["total"],
            transferred=counts["transferred"],
            skipped=counts["skipped"],
            failed=counts["failed"],
            pending=counts["pending"],
            target_chat_id=job["target_chat_id"],
            target_title=job.get("target_title"),
            copy_instead_of_forward=bool(job["copy_instead_of_forward"]),
            silent=bool(job["silent"]),
            dry_run=bool(job["dry_run"]),
            error_message=job.get("error_message"),
            created_at=datetime.fromisoformat(job["created_at"]),
            updated_at=datetime.fromisoformat(job["updated_at"]),
            recent_errors=recent,
        )


job_runner = JobRunner()
