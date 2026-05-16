from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from models import JobStatus, MessageItemStatus

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "transfer.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                target_chat_id INTEGER NOT NULL,
                target_title TEXT,
                copy_instead_of_forward INTEGER NOT NULL DEFAULT 0,
                silent INTEGER NOT NULL DEFAULT 1,
                dry_run INTEGER NOT NULL DEFAULT 0,
                batch_size INTEGER NOT NULL DEFAULT 50,
                batch_delay_seconds REAL NOT NULL DEFAULT 2.0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS job_items (
                job_id TEXT NOT NULL,
                source_message_id INTEGER NOT NULL,
                target_message_id INTEGER,
                status TEXT NOT NULL,
                reason TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (job_id, source_message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_job_items_status ON job_items(job_id, status);
            """
        )


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_job(
    target_chat_id: int,
    message_ids: list[int],
    *,
    target_title: str | None = None,
    copy_instead_of_forward: bool = False,
    silent: bool = True,
    dry_run: bool = False,
    batch_size: int = 50,
    batch_delay_seconds: float = 2.0,
) -> str:
    job_id = str(uuid4())
    now = _utc_now()
    status = JobStatus.COMPLETED.value if dry_run else JobStatus.PENDING.value
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO jobs (id, status, target_chat_id, target_title,
               copy_instead_of_forward, silent, dry_run, batch_size,
               batch_delay_seconds, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, status, target_chat_id, target_title,
             int(copy_instead_of_forward), int(silent), int(dry_run),
             batch_size, batch_delay_seconds, now, now),
        )
        for mid in sorted(set(message_ids)):
            conn.execute(
                "INSERT INTO job_items (job_id, source_message_id, status, updated_at) VALUES (?, ?, ?, ?)",
                (job_id, mid, MessageItemStatus.PENDING.value, now),
            )
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def update_job_status(job_id: str, status: JobStatus, error_message: str | None = None) -> None:
    now = _utc_now()
    with get_connection() as conn:
        if error_message is not None:
            conn.execute(
                "UPDATE jobs SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
                (status.value, error_message, now, job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, job_id),
            )


def get_job_counts(job_id: str) -> dict[str, int]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM job_items WHERE job_id = ? GROUP BY status",
            (job_id,),
        ).fetchall()
    counts = {s.value: 0 for s in MessageItemStatus}
    for row in rows:
        counts[row["status"]] = row["cnt"]
    return {
        "total": sum(counts.values()),
        "transferred": counts.get(MessageItemStatus.SENT.value, 0),
        "skipped": counts.get(MessageItemStatus.SKIPPED.value, 0),
        "failed": counts.get(MessageItemStatus.FAILED.value, 0),
        "pending": counts.get(MessageItemStatus.PENDING.value, 0),
    }


def get_pending_message_ids(job_id: str) -> list[int]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT source_message_id FROM job_items WHERE job_id = ? AND status = ? ORDER BY source_message_id",
            (job_id, MessageItemStatus.PENDING.value),
        ).fetchall()
    return [r["source_message_id"] for r in rows]


def is_message_sent(job_id: str, source_message_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM job_items WHERE job_id = ? AND source_message_id = ?",
            (job_id, source_message_id),
        ).fetchone()
    return bool(row and row["status"] == MessageItemStatus.SENT.value)


def update_job_item(
    job_id: str,
    source_message_id: int,
    status: MessageItemStatus,
    *,
    target_message_id: int | None = None,
    reason: str | None = None,
) -> None:
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """UPDATE job_items SET status = ?, target_message_id = ?, reason = ?, updated_at = ?
               WHERE job_id = ? AND source_message_id = ?""",
            (status.value, target_message_id, reason, now, job_id, source_message_id),
        )


def get_job_errors(job_id: str, *, limit: int = 500, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM job_items WHERE job_id = ? AND status IN (?, ?)",
            (job_id, MessageItemStatus.FAILED.value, MessageItemStatus.SKIPPED.value),
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT source_message_id, status, reason, target_message_id FROM job_items
               WHERE job_id = ? AND status IN (?, ?) ORDER BY source_message_id LIMIT ? OFFSET ?""",
            (job_id, MessageItemStatus.FAILED.value, MessageItemStatus.SKIPPED.value, limit, offset),
        ).fetchall()
    return [dict(r) for r in rows], total
