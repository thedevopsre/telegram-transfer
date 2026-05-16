from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AuthStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CODE_SENT = "code_sent"
    PASSWORD_REQUIRED = "password_required"
    CONNECTED = "connected"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class MessageItemStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    SKIPPED = "skipped"
    FAILED = "failed"


# --- Auth ---


class AuthStartRequest(BaseModel):
    api_id: int
    api_hash: str | None = None  # optional if TELEGRAM_API_HASH is set in .env
    phone: str


class AuthCodeRequest(BaseModel):
    code: str


class AuthPasswordRequest(BaseModel):
    password: str


class AuthStatusResponse(BaseModel):
    status: AuthStatus
    phone: str | None = None
    user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    message: str | None = None


class EnvDefaultsResponse(BaseModel):
    api_id: int | None = None
    api_hash: str | None = None  # always null; use api_hash_configured instead
    api_hash_configured: bool = False
    phone: str | None = None


# --- Dialogs ---


class DialogInfo(BaseModel):
    id: int
    title: str
    username: str | None = None
    is_channel: bool = False
    is_group: bool = False
    is_user: bool = False
    is_saved_messages: bool = False
    can_post: bool = False


class DialogsResponse(BaseModel):
    dialogs: list[DialogInfo]
    saved_messages_id: int | None = None


# --- Messages ---


class MessageInfo(BaseModel):
    id: int
    date: datetime
    text_snippet: str
    media_type: str | None = None
    is_album: bool = False
    grouped_id: int | None = None
    is_forwarded: bool = False
    forward_from: str | None = None
    sender_name: str | None = None
    has_media: bool = False


class MessagesResponse(BaseModel):
    messages: list[MessageInfo]
    page: int
    limit: int
    total_fetched: int
    has_more: bool


# --- Jobs ---


class JobCreateRequest(BaseModel):
    target_chat_id: int
    message_ids: list[int]
    copy_instead_of_forward: bool = False
    silent: bool = True
    batch_size: int = Field(default=50, ge=1, le=100)
    batch_delay_seconds: float = Field(default=2.0, ge=0.5, le=30.0)


class DryRunRequest(BaseModel):
    target_chat_id: int
    message_ids: list[int]


class DryRunResponse(BaseModel):
    would_transfer: int
    already_sent: int
    invalid_ids: list[int]
    target_title: str
    target_writable: bool
    warnings: list[str] = Field(default_factory=list)


class JobItemError(BaseModel):
    source_message_id: int
    status: MessageItemStatus
    reason: str
    target_message_id: int | None = None


class JobProgress(BaseModel):
    job_id: str
    status: JobStatus
    total: int
    transferred: int
    skipped: int
    failed: int
    pending: int
    target_chat_id: int
    target_title: str | None = None
    copy_instead_of_forward: bool = False
    silent: bool = True
    dry_run: bool = False
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class JobDetailResponse(JobProgress):
    recent_errors: list[JobItemError] = Field(default_factory=list)


class JobStartResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobActionResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class JobErrorsResponse(BaseModel):
    job_id: str
    errors: list[JobItemError]
    total: int


class GenericOk(BaseModel):
    ok: bool = True
    message: str | None = None
