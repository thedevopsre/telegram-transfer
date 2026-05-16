from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon import utils as telethon_utils
from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    MessageIdInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    RPCError,
    PasswordHashInvalidError,
    SendCodeUnavailableError,
    SessionPasswordNeededError,
)
from telethon.tl import functions as tl_functions
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantRequest
from telethon.tl.types import (
    Channel,
    ChannelParticipantAdmin,
    ChannelParticipantCreator,
    Chat,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
    User,
)

from models import AuthStatus, DialogInfo, MessageInfo

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SESSION_PATH = str(DATA_DIR / "telegram")
AUTH_STATE_PATH = DATA_DIR / "auth_pending.json"

SAVED_PEER = "me"


def _normalize_phone(phone: str) -> str:
    """E.164-style: digits only, leading +."""
    digits = re.sub(r"\D", "", phone.strip())
    if not digits:
        raise ValueError("Phone number is required.")
    return f"+{digits}"


def _normalize_code(code: str) -> str:
    """Telegram login codes are numeric (usually 5 digits)."""
    digits = re.sub(r"\D", "", code.strip())
    if not digits:
        raise ValueError("Login code is required.")
    return digits


class TelegramService:
    def __init__(self) -> None:
        self._client: TelegramClient | None = None
        self._api_id: int | None = None
        self._api_hash: str | None = None
        self._phone: str | None = None
        self._phone_code_hash: str | None = None
        self._lock = asyncio.Lock()
        self._auth_status = AuthStatus.DISCONNECTED
        self._user_info: dict[str, Any] = {}

    @property
    def auth_status(self) -> AuthStatus:
        return self._auth_status

    @property
    def is_connected(self) -> bool:
        return self._auth_status == AuthStatus.CONNECTED

    async def refresh_connection_state(self) -> AuthStatus:
        """Sync auth status from an on-disk session (e.g. after server restart)."""
        if self._client and await self._client.is_user_authorized():
            me = await self._client.get_me()
            self._set_connected(me)
            return AuthStatus.CONNECTED
        if self._auth_status == AuthStatus.CONNECTED:
            self._auth_status = AuthStatus.DISCONNECTED
        return self._auth_status

    def get_env_defaults(self) -> dict[str, Any]:
        """Pre-fill login form. Never exposes api_hash to the browser."""
        api_id = os.getenv("TELEGRAM_API_ID")
        phone = os.getenv("TELEGRAM_PHONE")
        return {
            "api_id": int(api_id) if api_id and api_id.isdigit() else None,
            "api_hash": None,
            "api_hash_configured": bool(os.getenv("TELEGRAM_API_HASH")),
            "phone": phone or None,
        }

    def _resolve_api_hash(self, api_hash: str | None) -> str:
        resolved = (api_hash or os.getenv("TELEGRAM_API_HASH") or "").strip()
        if not resolved:
            raise ValueError(
                "API hash is required. Set TELEGRAM_API_HASH in .env or enter it in the login form."
            )
        return resolved

    async def _ensure_client(self, api_id: int, api_hash: str) -> TelegramClient:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if self._client is None or self._api_id != api_id or self._api_hash != api_hash:
            if self._client:
                await self._client.disconnect()
            self._client = TelegramClient(
                SESSION_PATH,
                api_id,
                api_hash,
                device_model="Saved Messages Transfer",
                system_version="macOS",
                app_version="1.0",
            )
            self._api_id = api_id
            self._api_hash = api_hash
        return self._client

    def _save_auth_state(self, *, needs_password: bool = False) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        AUTH_STATE_PATH.write_text(
            json.dumps(
                {
                    "phone": self._phone,
                    "phone_code_hash": self._phone_code_hash,
                    "api_id": self._api_id,
                    "needs_password": needs_password,
                }
            ),
            encoding="utf-8",
        )

    def _load_auth_state(self) -> bool:
        if not AUTH_STATE_PATH.exists():
            return False
        try:
            data = json.loads(AUTH_STATE_PATH.read_text(encoding="utf-8"))
            self._phone = data.get("phone") or self._phone
            self._phone_code_hash = data.get("phone_code_hash") or self._phone_code_hash
            if data.get("api_id") and not self._api_id:
                self._api_id = data["api_id"]
            if data.get("needs_password"):
                self._auth_status = AuthStatus.PASSWORD_REQUIRED
                return True
            return bool(self._phone and self._phone_code_hash)
        except (json.JSONDecodeError, OSError):
            return False

    def _clear_auth_state(self) -> None:
        if AUTH_STATE_PATH.exists():
            AUTH_STATE_PATH.unlink(missing_ok=True)

    def _clear_telethon_code_hash(self, client: TelegramClient, phone: str) -> None:
        """Drop cached hash so the next send uses SendCodeRequest, not ResendCodeRequest."""
        key = telethon_utils.parse_phone(phone) or phone
        hashes = getattr(client, "_phone_code_hash", None)
        if isinstance(hashes, dict):
            hashes.pop(key, None)

    def _auth_delivery_hint(self, sent: Any) -> str | None:
        code_type = getattr(sent, "type", None)
        if code_type is None:
            return None
        name = type(code_type).__name__
        if "App" in name:
            return "Check the Telegram app chat from “Telegram” for your login code."
        if "Sms" in name or "Call" in name:
            return "Check SMS or the call ending with the code digits."
        return None

    def _raise_auth_error(self, exc: BaseException) -> None:
        if isinstance(exc, FloodWaitError):
            mins = max(1, (exc.seconds + 59) // 60)
            raise ValueError(
                f"Too many login attempts. Wait {exc.seconds} seconds "
                f"(about {mins} minute(s)), then try again."
            ) from None
        if isinstance(exc, SendCodeUnavailableError):
            raise ValueError(
                "Telegram will not send more codes to this number right now "
                "(app, SMS, and call options were already used). "
                "Use the latest code already in your Telegram app, or wait several hours "
                "before requesting again. Avoid clicking Resend repeatedly."
            ) from None
        if isinstance(exc, PhoneCodeExpiredError):
            raise ValueError(
                "The previous code expired. Click “Send login code” on the first screen "
                "for a brand-new code (wait a few minutes if you were rate-limited)."
            ) from None
        raise exc

    async def _clear_local_session(
        self, *, remote_log_out: bool = False, wipe_transfer_data: bool = False
    ) -> None:
        if self._client:
            try:
                if remote_log_out and await self._client.is_user_authorized():
                    await self._client.log_out()
            except Exception:
                logger.warning("Telegram log_out failed; clearing local session anyway")
            try:
                if self._phone:
                    self._clear_telethon_code_hash(self._client, self._phone)
                await self._client.disconnect()
            except Exception:
                logger.debug("disconnect failed", exc_info=True)
        self._client = None
        self._api_id = None
        self._api_hash = None
        self._phone = None
        self._phone_code_hash = None
        self._auth_status = AuthStatus.DISCONNECTED
        self._user_info = {}
        self._clear_auth_state()
        for path in (
            Path(f"{SESSION_PATH}.session"),
            Path(f"{SESSION_PATH}.session-journal"),
        ):
            path.unlink(missing_ok=True)
        if wipe_transfer_data:
            from db import DB_PATH as transfer_db

            for path in (transfer_db, DATA_DIR / "transfer.log"):
                path.unlink(missing_ok=True)

    async def reset_auth(self) -> None:
        """Clear local login state (keeps Telegram server session active)."""
        async with self._lock:
            await self._clear_local_session(remote_log_out=False)

    async def logout(self) -> None:
        """Log out from Telegram and delete the local session."""
        async with self._lock:
            await self._clear_local_session(remote_log_out=True)

    async def clean_session(self) -> None:
        """Log out, remove Telegram session, and wipe local transfer history/logs."""
        from jobs import job_runner

        job_runner.cancel_all()
        async with self._lock:
            await self._clear_local_session(remote_log_out=True, wipe_transfer_data=True)

    async def start_auth(self, api_id: int, api_hash: str | None, phone: str) -> AuthStatus:
        api_hash = self._resolve_api_hash(api_hash)
        async with self._lock:
            client = await self._ensure_client(api_id, api_hash)
            await client.connect()
            self._phone = _normalize_phone(phone)

            if await client.is_user_authorized():
                me = await client.get_me()
                self._set_connected(me)
                self._clear_auth_state()
                return AuthStatus.CONNECTED

            # Always request a fresh code (ResendCodeRequest only via resend_code()).
            self._clear_telethon_code_hash(client, self._phone)
            try:
                sent = await client.send_code_request(self._phone)
            except (FloodWaitError, SendCodeUnavailableError) as e:
                self._raise_auth_error(e)

            self._phone_code_hash = sent.phone_code_hash
            self._auth_status = AuthStatus.CODE_SENT
            self._save_auth_state()
            hint = self._auth_delivery_hint(sent)
            if hint:
                logger.info("Login code sent for %s — %s", self._phone[:4] + "…", hint)
            else:
                logger.info("Login code sent for %s", self._phone[:4] + "…")
            return AuthStatus.CODE_SENT

    async def resend_code(self) -> AuthStatus:
        """Resend via Telegram ResendCodeRequest (same login attempt, new delivery)."""
        async with self._lock:
            if not self._client:
                raise ValueError("Auth not started. Use “Send login code” on the first screen.")

            if not self._phone_code_hash:
                self._load_auth_state()

            if not self._phone or not self._phone_code_hash:
                raise ValueError(
                    "No active code request. Go back and click “Send login code”."
                )

            if not self._client.is_connected():
                await self._client.connect()

            try:
                sent = await self._client(
                    tl_functions.auth.ResendCodeRequest(
                        self._phone, self._phone_code_hash
                    )
                )
            except (FloodWaitError, SendCodeUnavailableError, PhoneCodeExpiredError) as e:
                self._raise_auth_error(e)

            if getattr(sent, "phone_code_hash", None):
                self._phone_code_hash = sent.phone_code_hash
            self._auth_status = AuthStatus.CODE_SENT
            self._save_auth_state()
            return AuthStatus.CODE_SENT

    async def submit_code(self, code: str) -> AuthStatus:
        async with self._lock:
            if not self._client:
                raise ValueError("Auth not started. Click “Send login code” first.")

            if not self._phone_code_hash:
                self._load_auth_state()

            if not self._phone or not self._phone_code_hash:
                raise ValueError(
                    "Login session expired. Go back and click “Send login code” again."
                )

            if not self._client.is_connected():
                await self._client.connect()

            normalized = _normalize_code(code)

            try:
                # Use Telethon’s internal state from send_code_request (most reliable).
                await self._client.sign_in(code=normalized)
            except SessionPasswordNeededError:
                self._auth_status = AuthStatus.PASSWORD_REQUIRED
                self._save_auth_state(needs_password=True)
                logger.info("2FA password required for %s", self._phone[:4] + "…")
                return AuthStatus.PASSWORD_REQUIRED
            except PhoneCodeInvalidError:
                raise ValueError(
                    "Invalid login code. Use the newest code from Telegram "
                    "(message titled “Login code”), then request a new code if needed."
                ) from None
            except PhoneCodeExpiredError:
                self._phone_code_hash = None
                self._clear_auth_state()
                raise ValueError(
                    "Code expired. Go back and click “Send login code” to get a new one."
                ) from None

            me = await self._client.get_me()
            self._set_connected(me)
            self._clear_auth_state()
            return AuthStatus.CONNECTED

    async def submit_password(self, password: str) -> AuthStatus:
        async with self._lock:
            if not self._client:
                raise ValueError("Auth not started.")

            if not self._client.is_connected():
                await self._client.connect()

            if self._auth_status != AuthStatus.PASSWORD_REQUIRED:
                self._load_auth_state()

            pwd = password.strip()
            if not pwd:
                raise ValueError(
                    "Enter your Telegram cloud password (2FA). "
                    "Settings → Privacy and Security → Two-Step Verification."
                )

            try:
                await self._client.sign_in(password=pwd)
            except PasswordHashInvalidError:
                raise ValueError(
                    "Wrong 2FA password. Use your Telegram cloud password "
                    "(Two-Step Verification), not the SMS login code."
                ) from None
            except SessionPasswordNeededError:
                raise ValueError(
                    "Password still required. Submit your Telegram cloud password "
                    "(Two-Step Verification password)."
                ) from None

            me = await self._client.get_me()
            self._set_connected(me)
            self._clear_auth_state()
            return AuthStatus.CONNECTED

    def _set_connected(self, me: User) -> None:
        self._auth_status = AuthStatus.CONNECTED
        first = (me.first_name or "").strip()
        if not first:
            first = me.username or f"User {me.id}"
        self._user_info = {
            "user_id": me.id,
            "username": me.username,
            "first_name": first,
            "phone": self._phone or getattr(me, "phone", None),
        }

    async def ensure_connected(self) -> TelegramClient:
        if not self._client:
            api_id = os.getenv("TELEGRAM_API_ID")
            api_hash = os.getenv("TELEGRAM_API_HASH")
            if api_id and api_hash:
                client = await self._ensure_client(int(api_id), api_hash)
                await client.connect()
                if await client.is_user_authorized():
                    me = await client.get_me()
                    self._set_connected(me)
                    return client
            raise RuntimeError("Not logged in")

        if not await self._client.is_user_authorized():
            self._auth_status = AuthStatus.DISCONNECTED
            raise RuntimeError("Session expired. Please log in again.")

        if not self._client.is_connected():
            await self._client.connect()

        return self._client

    def status_dict(self) -> dict[str, Any]:
        if self._auth_status != AuthStatus.CONNECTED:
            self._load_auth_state()
        return {
            "status": self._auth_status,
            "phone": self._user_info.get("phone") or self._phone,
            "user_id": self._user_info.get("user_id"),
            "username": self._user_info.get("username"),
            "first_name": self._user_info.get("first_name"),
        }

    async def load_session_if_exists(self) -> AuthStatus:
        defaults = self.get_env_defaults()
        if not defaults.get("api_id") or not defaults.get("api_hash"):
            session_file = Path(f"{SESSION_PATH}.session")
            if not session_file.exists():
                return AuthStatus.DISCONNECTED
            return AuthStatus.DISCONNECTED

        try:
            client = await self._ensure_client(
                defaults["api_id"],  # type: ignore[arg-type]
                defaults["api_hash"],  # type: ignore[arg-type]
            )
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                self._set_connected(me)
                return AuthStatus.CONNECTED
        except Exception:
            logger.exception("Failed to restore session")
        return AuthStatus.DISCONNECTED

    async def list_dialogs(self) -> tuple[list[DialogInfo], int | None]:
        client = await self.ensure_connected()
        me = await client.get_me()
        saved_id = me.id if me else None

        dialogs: list[DialogInfo] = []
        dialogs.append(
            DialogInfo(
                id=saved_id or 0,
                title="Saved Messages",
                username=None,
                is_user=True,
                is_saved_messages=True,
                can_post=True,
            )
        )

        seen_ids: set[int] = set()
        for archived in (False, True):
            async for dialog in client.iter_dialogs(archived=archived):
                entity = dialog.entity
                if dialog.id in seen_ids:
                    continue
                seen_ids.add(dialog.id)

                title = (dialog.title or "Unknown").strip()
                username = getattr(entity, "username", None)
                is_channel = isinstance(entity, Channel)
                is_group = isinstance(entity, Chat)
                is_user = isinstance(entity, User)

                # Only list groups/channels as transfer targets (not DMs).
                if not is_channel and not is_group:
                    continue

                can_post = False
                if is_channel:
                    can_post = await self._can_post_to_channel(client, entity)
                elif is_group:
                    try:
                        perms = await client.get_permissions(entity, "me")
                        can_post = bool(
                            perms.send_messages
                            or getattr(perms, "is_admin", False)
                            or getattr(perms, "is_creator", False)
                        )
                    except Exception:
                        can_post = not getattr(entity, "left", False)

                dialogs.append(
                    DialogInfo(
                        id=dialog.id,
                        title=title + (" (archived)" if archived else ""),
                        username=username,
                        is_channel=is_channel,
                        is_group=is_group,
                        is_user=False,
                        is_saved_messages=False,
                        can_post=can_post,
                    )
                )

        dialogs.sort(key=lambda d: (not d.can_post, d.title.lower()))
        return dialogs, saved_id

    async def _can_post_to_channel(self, client: TelegramClient, channel: Channel) -> bool:
        if getattr(channel, "left", False) or getattr(channel, "restricted", False):
            return False

        # Flags on the channel entity (often set for owners of private channels).
        if getattr(channel, "creator", False):
            return True
        admin_rights = getattr(channel, "admin_rights", None)
        if admin_rights and getattr(admin_rights, "post_messages", False):
            return True

        try:
            perms = await client.get_permissions(channel, "me")
            if getattr(perms, "is_creator", False) or getattr(perms, "is_admin", False):
                return True
            if getattr(perms, "post_messages", False) or getattr(perms, "send_messages", False):
                return True
        except Exception:
            pass

        if getattr(channel, "broadcast", False):
            try:
                result = await client(
                    GetParticipantRequest(channel, await client.get_me())
                )
                participant = result.participant
                if isinstance(participant, ChannelParticipantCreator):
                    return True
                if isinstance(participant, ChannelParticipantAdmin):
                    return bool(
                        participant.admin_rights
                        and participant.admin_rights.post_messages
                    )
            except Exception as exc:
                logger.debug("GetParticipantRequest failed for %s: %s", channel.id, exc)

            # Private broadcast channel you own may not expose participant info until
            # full fetch — if you're in the dialog and didn't leave, allow and validate later.
            if not getattr(channel, "username", None) and not getattr(channel, "left", False):
                return True

        return False

    async def validate_target_writable(self, target_chat_id: int) -> tuple[bool, str, str]:
        client = await self.ensure_connected()
        try:
            entity = await client.get_entity(target_chat_id)
        except Exception as e:
            return False, "Unknown", f"Cannot resolve target chat: {e}"

        title = getattr(entity, "title", None) or getattr(entity, "first_name", "Unknown")

        if isinstance(entity, Channel):
            if not await self._can_post_to_channel(client, entity):
                return (
                    False,
                    title,
                    "You cannot post to this channel. Join as admin with post permission.",
                )
            return True, title, ""

        if isinstance(entity, Chat):
            try:
                perms = await client.get_permissions(entity, "me")
                if not perms.send_messages:
                    return False, title, "You cannot send messages to this group."
            except Exception as e:
                return False, title, f"Permission check failed: {e}"
            return True, title, ""

        return False, title, "Target must be a channel or group, not a private user chat."

    def _media_type(self, message: Message) -> str | None:
        if not message.media:
            return None
        if isinstance(message.media, MessageMediaPhoto):
            return "photo"
        if isinstance(message.media, MessageMediaDocument):
            doc = message.media.document
            if doc:
                for attr in doc.attributes:
                    name = type(attr).__name__
                    if "Video" in name:
                        return "video"
                    if "Audio" in name or "Voice" in name:
                        return "audio"
                    if "Sticker" in name:
                        return "sticker"
            return "document"
        if isinstance(message.media, MessageMediaWebPage):
            return "webpage"
        return type(message.media).__name__

    def _message_to_info(self, message: Message) -> MessageInfo:
        text = message.message or ""
        snippet = text[:200] + ("…" if len(text) > 200 else "")
        if not snippet and message.media:
            snippet = f"[{self._media_type(message) or 'media'}]"

        forward_from = None
        is_forwarded = bool(message.fwd_from)
        if message.fwd_from:
            if message.fwd_from.from_name:
                forward_from = message.fwd_from.from_name
            elif message.fwd_from.from_id:
                forward_from = str(message.fwd_from.from_id)

        return MessageInfo(
            id=message.id,
            date=message.date.replace(tzinfo=timezone.utc)
            if message.date.tzinfo is None
            else message.date,
            text_snippet=snippet,
            media_type=self._media_type(message),
            is_album=message.grouped_id is not None,
            grouped_id=message.grouped_id,
            is_forwarded=is_forwarded,
            forward_from=forward_from,
            sender_name=None,
            has_media=message.media is not None,
        )

    async def fetch_saved_messages(
        self,
        *,
        page: int = 1,
        limit: int = 50,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        media_only: bool = False,
        text_only: bool = False,
        forwarded_only: bool = False,
    ) -> tuple[list[MessageInfo], bool]:
        client = await self.ensure_connected()
        offset_id = 0
        # Telethon uses offset for pagination; we scan and filter client-side for flexibility
        collected: list[MessageInfo] = []
        scan_batch = max(limit * 3, 100)
        max_scan = 5000
        scanned = 0
        skip_until = (page - 1) * limit

        async for message in client.iter_messages(
            SAVED_PEER,
            search=search if search else None,
            offset_id=offset_id,
            reverse=False,
        ):
            if not isinstance(message, Message):
                continue
            scanned += 1
            if scanned > max_scan:
                break

            msg_date = message.date
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)

            if date_from and msg_date < date_from:
                continue
            if date_to and msg_date > date_to:
                continue
            if media_only and not message.media:
                continue
            if text_only and (not message.message or not message.message.strip()):
                continue
            if forwarded_only and not message.fwd_from:
                continue

            info = self._message_to_info(message)
            if skip_until > 0:
                skip_until -= 1
                continue
            collected.append(info)
            if len(collected) >= limit + 1:
                break

        has_more = len(collected) > limit
        if has_more:
            collected = collected[:limit]
        return collected, has_more

    async def fetch_all_matching_ids(
        self,
        message_ids: list[int] | None,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        media_only: bool = False,
        text_only: bool = False,
        forwarded_only: bool = False,
        max_messages: int = 10000,
    ) -> list[int]:
        if message_ids is not None:
            return sorted(message_ids)

        client = await self.ensure_connected()
        ids: list[int] = []
        async for message in client.iter_messages(SAVED_PEER, search=search or None):
            if not isinstance(message, Message):
                continue
            msg_date = message.date
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            if date_from and msg_date < date_from:
                continue
            if date_to and msg_date > date_to:
                continue
            if media_only and not message.media:
                continue
            if text_only and (not message.message or not message.message.strip()):
                continue
            if forwarded_only and not message.fwd_from:
                continue
            ids.append(message.id)
            if len(ids) >= max_messages:
                break
        return sorted(ids, reverse=False)

    async def forward_batch(
        self,
        target_chat_id: int,
        message_ids: list[int],
        *,
        copy_instead_of_forward: bool = False,
        silent: bool = True,
    ) -> dict[int, int | None]:
        """Forward messages; returns map source_id -> target_id or None on failure."""
        client = await self.ensure_connected()
        target = await client.get_entity(target_chat_id)
        results: dict[int, int | None] = {}

        try:
            updates = await client.forward_messages(
                entity=target,
                messages=message_ids,
                from_peer=SAVED_PEER,
                silent=silent,
                drop_author=copy_instead_of_forward,
            )
            if updates:
                forwarded = updates if isinstance(updates, list) else [updates]
                for src, upd in zip(message_ids, forwarded):
                    results[src] = getattr(upd, "id", None)
            else:
                for mid in message_ids:
                    results[mid] = None
        except FloodWaitError:
            raise
        except MessageIdInvalidError:
            for mid in message_ids:
                results[mid] = None
        except RPCError as e:
            err = str(e)
            if "CHAT_FORWARDS_RESTRICTED" in err or "protected" in err.lower():
                for mid in message_ids:
                    results[mid] = None
                raise
            raise

        for mid in message_ids:
            if mid not in results:
                results[mid] = None
        return results

    async def message_exists(self, message_id: int) -> bool:
        client = await self.ensure_connected()
        msg = await client.get_messages(SAVED_PEER, ids=message_id)
        if isinstance(msg, list):
            return bool(msg) and msg[0] is not None
        return msg is not None


telegram_service = TelegramService()
