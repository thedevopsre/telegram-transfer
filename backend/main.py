from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Allow running as `python main.py` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
from jobs import job_runner
from models import (
    AuthCodeRequest,
    AuthPasswordRequest,
    AuthStartRequest,
    AuthStatus,
    AuthStatusResponse,
    DialogsResponse,
    DryRunRequest,
    DryRunResponse,
    EnvDefaultsResponse,
    JobActionResponse,
    JobCreateRequest,
    JobDetailResponse,
    JobErrorsResponse,
    JobItemError,
    JobStartResponse,
    JobStatus,
    MessageItemStatus,
    MessagesResponse,
)
from telegram_client import telegram_service

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# Never log sensitive fields
logging.getLogger("telethon").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    await telegram_service.load_session_if_exists()
    await job_runner.resume_incomplete_on_startup()
    yield


app = FastAPI(
    title="Telegram Saved Messages Transfer",
    description="Local-only tool to forward Saved Messages to a channel",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


async def require_logged_in() -> None:
    try:
        await telegram_service.ensure_connected()
        await telegram_service.refresh_connection_state()
    except RuntimeError:
        raise HTTPException(status_code=401, detail="Not logged in") from None
    if not telegram_service.is_connected:
        raise HTTPException(status_code=401, detail="Not logged in")


# --- Auth ---


@app.get("/api/env-defaults", response_model=EnvDefaultsResponse)
async def env_defaults():
    d = telegram_service.get_env_defaults()
    return EnvDefaultsResponse(**d)


@app.get("/api/app-info")
async def app_info():
    """Help the UI detect stale cached frontend bundles."""
    index_path = FRONTEND_DIST / "index.html"
    js_bundle = None
    if index_path.exists():
        text = index_path.read_text(encoding="utf-8")
        for part in text.split('"'):
            if part.startswith("/assets/index-") and part.endswith(".js"):
                js_bundle = part
                break
    return {
        "frontend_built": index_path.exists(),
        "js_bundle": js_bundle,
        "frontend_dist": str(FRONTEND_DIST),
    }


@app.post("/auth/logout")
async def auth_logout():
    job_runner.cancel_all()
    await telegram_service.logout()
    return {"ok": True, "message": "Logged out. Local Telegram session removed."}


@app.post("/auth/clean-session")
async def auth_clean_session():
    """Log out and delete session plus local transfer database and logs."""
    await telegram_service.clean_session()
    db.init_db()
    return {
        "ok": True,
        "message": "Session cleared. Transfer history and logs removed. Log in again to continue.",
    }


@app.post("/auth/start", response_model=AuthStatusResponse)
async def auth_start(body: AuthStartRequest):
    try:
        api_hash = body.api_hash.strip() if body.api_hash else None
        status = await telegram_service.start_auth(
            body.api_id, api_hash, body.phone.strip()
        )
        msg = (
            "Code sent. Open the Telegram app → chat from “Telegram” for the login code."
            if status == AuthStatus.CODE_SENT
            else None
        )
        return AuthStatusResponse(
            status=status, phone=body.phone.strip(), message=msg
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        logging.getLogger(__name__).warning("auth/start failed", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail="Could not send login code. Check API credentials and phone number.",
        ) from None


@app.post("/auth/resend", response_model=AuthStatusResponse)
async def auth_resend():
    try:
        status = await telegram_service.resend_code()
        return AuthStatusResponse(
            status=status,
            message="Code resent. Use the newest login code in your Telegram app.",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logging.getLogger(__name__).warning("auth/resend failed: %s", type(e).__name__)
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/auth/reset")
async def auth_reset():
    """Clear partial session and code state after too many failed/resend attempts."""
    await telegram_service.reset_auth()
    return {"ok": True, "message": "Login reset. You can send a new code from the first screen."}


def _auth_response(status: AuthStatus, message: str | None = None) -> AuthStatusResponse:
    info = telegram_service.status_dict()
    return AuthStatusResponse(
        status=status,
        phone=info.get("phone"),
        user_id=info.get("user_id"),
        username=info.get("username"),
        first_name=info.get("first_name"),
        message=message,
    )


@app.post("/auth/code", response_model=AuthStatusResponse)
async def auth_code(body: AuthCodeRequest):
    try:
        status = await telegram_service.submit_code(body.code)
        if status == AuthStatus.PASSWORD_REQUIRED:
            return _auth_response(
                status,
                message=(
                    "Login code accepted. Your account uses Two-Step Verification — "
                    "enter your Telegram cloud password below (not another SMS code)."
                ),
            )
        return _auth_response(status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logging.getLogger(__name__).warning("auth/code failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=400,
            detail="Sign-in failed. Request a new code or delete data/telegram.session and retry.",
        ) from e


@app.post("/auth/password", response_model=AuthStatusResponse)
async def auth_password(body: AuthPasswordRequest):
    try:
        status = await telegram_service.submit_password(body.password)
        return _auth_response(status, message="Signed in successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logging.getLogger(__name__).warning("auth/password failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=400,
            detail="Could not verify 2FA password. Check your cloud password and try again.",
        ) from e


@app.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status():
    try:
        await telegram_service.refresh_connection_state()
    except Exception:
        pass
    info = telegram_service.status_dict()
    st = info["status"]
    if not isinstance(st, AuthStatus):
        st = AuthStatus(st)
    return AuthStatusResponse(
        status=st,
        phone=info.get("phone"),
        user_id=info.get("user_id"),
        username=info.get("username"),
        first_name=info.get("first_name"),
    )


# --- Dialogs ---


@app.get("/dialogs", response_model=DialogsResponse)
async def list_dialogs(_: None = Depends(require_logged_in)):
    dialogs, saved_id = await telegram_service.list_dialogs()
    return DialogsResponse(dialogs=dialogs, saved_messages_id=saved_id)


# --- Messages ---


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {value}") from None


@app.get("/messages", response_model=MessagesResponse)
async def get_messages(
    saved: bool = Query(True),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    media_only: bool = False,
    text_only: bool = False,
    forwarded_only: bool = False,
    _: None = Depends(require_logged_in),
):
    if not saved:
        raise HTTPException(status_code=400, detail="Only saved=true is supported")

    messages, has_more = await telegram_service.fetch_saved_messages(
        page=page,
        limit=limit,
        date_from=_parse_datetime(date_from),
        date_to=_parse_datetime(date_to),
        search=search,
        media_only=media_only,
        text_only=text_only,
        forwarded_only=forwarded_only,
    )
    return MessagesResponse(
        messages=messages,
        page=page,
        limit=limit,
        total_fetched=len(messages),
        has_more=has_more,
    )


@app.get("/messages/ids")
async def get_all_matching_ids(
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    media_only: bool = False,
    text_only: bool = False,
    forwarded_only: bool = False,
    _: None = Depends(require_logged_in),
):
    ids = await telegram_service.fetch_all_matching_ids(
        None,
        date_from=_parse_datetime(date_from),
        date_to=_parse_datetime(date_to),
        search=search,
        media_only=media_only,
        text_only=text_only,
        forwarded_only=forwarded_only,
    )
    return {"ids": ids, "count": len(ids)}


# --- Jobs ---


@app.post("/jobs/dry-run", response_model=DryRunResponse)
async def jobs_dry_run(body: DryRunRequest, _: None = Depends(require_logged_in)):
    if not body.message_ids:
        raise HTTPException(status_code=400, detail="No messages selected")
    return await job_runner.dry_run(body.target_chat_id, body.message_ids)


@app.post("/jobs/start", response_model=JobStartResponse)
async def jobs_start(body: JobCreateRequest, _: None = Depends(require_logged_in)):
    if not body.message_ids:
        raise HTTPException(status_code=400, detail="No messages selected")
    try:
        job_id = await job_runner.start_job(
            body.target_chat_id,
            body.message_ids,
            copy_instead_of_forward=body.copy_instead_of_forward,
            silent=body.silent,
            batch_size=body.batch_size,
            batch_delay_seconds=body.batch_delay_seconds,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return JobStartResponse(job_id=job_id, status=JobStatus.RUNNING)


@app.post("/jobs/{job_id}/pause", response_model=JobActionResponse)
async def jobs_pause(job_id: str):
    if not job_runner.pause(job_id):
        raise HTTPException(status_code=400, detail="Cannot pause job")
    return JobActionResponse(job_id=job_id, status=JobStatus.PAUSED, message="Paused")


@app.post("/jobs/{job_id}/resume", response_model=JobActionResponse)
async def jobs_resume(job_id: str):
    if not job_runner.resume(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return JobActionResponse(job_id=job_id, status=JobStatus.RUNNING, message="Resumed")


@app.post("/jobs/{job_id}/cancel", response_model=JobActionResponse)
async def jobs_cancel(job_id: str):
    if not job_runner.cancel(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return JobActionResponse(
        job_id=job_id, status=JobStatus.CANCELLED, message="Cancelled"
    )


@app.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def jobs_get(job_id: str):
    detail = job_runner.build_job_detail(job_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Job not found")
    return detail


@app.get("/jobs/{job_id}/errors", response_model=JobErrorsResponse)
async def jobs_errors(job_id: str, limit: int = Query(500, ge=1, le=5000), offset: int = 0):
    if not db.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    rows, total = db.get_job_errors(job_id, limit=limit, offset=offset)
    errors = [
        JobItemError(
            source_message_id=r["source_message_id"],
            status=MessageItemStatus(r["status"]),
            reason=r["reason"] or "",
            target_message_id=r["target_message_id"],
        )
        for r in rows
    ]
    return JobErrorsResponse(job_id=job_id, errors=errors, total=total)


# --- Static frontend ---


@app.get("/")
async def index():
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path, headers=NO_CACHE)
    return {
        "message": "Frontend not built. Run: cd frontend && npm install && npm run build",
        "api_docs": "/docs",
    }


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api") or full_path.startswith("auth") or full_path.startswith("jobs") or full_path.startswith("dialogs") or full_path.startswith("messages"):
            raise HTTPException(status_code=404)
        if ".." in full_path or full_path.startswith(("/", "\\")):
            raise HTTPException(status_code=404, detail="Not found")
        # Missing old hashed JS/CSS must 404 — not index.html (breaks cached browsers).
        if full_path.startswith("assets/") or full_path.endswith((".js", ".css", ".map")):
            raise HTTPException(status_code=404, detail="Asset not found — hard-refresh the page")
        file_path = (FRONTEND_DIST / full_path).resolve()
        if not str(file_path).startswith(str(FRONTEND_DIST.resolve())):
            raise HTTPException(status_code=404, detail="Not found")
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIST / "index.html", headers=NO_CACHE)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
