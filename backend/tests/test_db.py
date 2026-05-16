import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db
from models import JobStatus, MessageItemStatus


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    db.init_db()


def test_idempotency_sent_check():
    job_id = db.create_job(1, [10, 20])
    db.update_job_item(job_id, 10, MessageItemStatus.SENT, target_message_id=99)
    assert db.is_message_sent(job_id, 10)
    assert not db.is_message_sent(job_id, 20)


def test_pending_ids():
    job_id = db.create_job(1, [1, 2, 3])
    db.update_job_item(job_id, 1, MessageItemStatus.SENT, target_message_id=1)
    assert db.get_pending_message_ids(job_id) == [2, 3]
