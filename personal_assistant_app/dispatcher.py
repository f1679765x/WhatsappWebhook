import base64
import logging
import os
from pathlib import Path

import asyncpg

from personal_assistant_app.agent_loop import TRIGGERS, run_agent_loop
from personal_assistant_app.mcp_client import MCPClientManager
from personal_assistant_app.session_manager import SessionManager

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", r"D:\WhatsappData"))

TRIGGER_TYPES = {"incomingMessageReceived"}
TEXT_TYPES = {"textMessage", "extendedTextMessage", "quotedMessage"}
MEDIA_TYPES = {"imageMessage", "audioMessage", "videoMessage", "documentMessage"}


async def _fetch_archived(msg_id: str, db_pool: asyncpg.Pool) -> dict | None:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT text_message, file_path, file_name, file_mime, caption FROM messages WHERE id = $1",
            msg_id,
        )
    return dict(row) if row else None


def _image_content_blocks(file_path: Path, mime: str, user_text: str) -> list:
    b64 = base64.standard_b64encode(file_path.read_bytes()).decode()
    blocks = [{"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}]
    if user_text:
        blocks.append({"type": "text", "text": user_text})
    return blocks


async def _extract_quoted_content(payload: dict, db_pool: asyncpg.Pool) -> tuple[str, str | list]:
    """Handle quotedMessage type. Returns (trigger_text, claude_content)."""
    md = payload.get("messageData", {})
    user_text = md.get("extendedTextMessageData", {}).get("text", "")
    quoted = md.get("quotedMessage", {})
    quoted_type = quoted.get("typeMessage", "")
    stanza_id = quoted.get("stanzaId", "")

    if quoted_type == "audioMessage" and stanza_id:
        archived = await _fetch_archived(stanza_id, db_pool)
        transcript = (archived or {}).get("text_message") or ""
        if transcript:
            content = f'[Quoted audio] Transcription: "{transcript}"\n{user_text}'
        else:
            content = f"[Quoted audio — transcription unavailable]\n{user_text}"
        return user_text, content

    if quoted_type == "imageMessage" and stanza_id:
        archived = await _fetch_archived(stanza_id, db_pool)
        if archived and archived.get("file_path"):
            file_path = DATA_DIR / archived["file_path"]
            mime = archived.get("file_mime") or "image/jpeg"
            try:
                content = _image_content_blocks(file_path, mime, user_text)
                return user_text, content
            except Exception as e:
                log.error("Could not read quoted image %s: %s", file_path, e)

    if quoted_type == "videoMessage":
        content = f"The user quoted a video file and said: \"{user_text}\". You cannot watch or analyse videos. Politely let them know you can't process video, and suggest they describe what they need help with instead."
        return user_text, content

    if quoted_type == "documentMessage":
        fname = quoted.get("fileName", "")
        caption = quoted.get("caption", "")
        content = f"[Quoted document: {fname}]{': ' + caption if caption else ''}\n{user_text}"
        return user_text, content

    # Plain text or unknown — extract textMessage directly
    quoted_text = quoted.get("textMessage", "") or quoted.get("text", "")
    if quoted_text:
        content = f'[Quoted message]: "{quoted_text}"\n{user_text}'
    else:
        content = user_text
    return user_text, content


def _extract_simple_text(payload: dict) -> str:
    md = payload.get("messageData", {})
    tm = md.get("typeMessage", "")
    if tm == "textMessage":
        return md.get("textMessageData", {}).get("textMessage", "")
    if tm == "extendedTextMessage":
        return md.get("extendedTextMessageData", {}).get("text", "")
    return ""


async def _build_media_content(payload: dict, db_pool: asyncpg.Pool) -> tuple[str, str | list]:
    """For direct media messages. Returns (trigger_text, claude_content)."""
    md = payload.get("messageData", {})
    tm = md.get("typeMessage", "")
    msg_id = payload.get("idMessage", "")
    caption = md.get("fileMessageData", {}).get("caption", "") or ""
    archived = await _fetch_archived(msg_id, db_pool)

    if tm == "audioMessage":
        transcript = (archived or {}).get("text_message") or ""
        content = f"[Audio message] Transcription: {transcript}" if transcript else "[Audio message — transcription unavailable]"
        if caption:
            content += f"\n{caption}"
        return caption, content

    if tm == "imageMessage" and archived and archived.get("file_path"):
        file_path = DATA_DIR / archived["file_path"]
        mime = archived.get("file_mime") or "image/jpeg"
        try:
            content = _image_content_blocks(file_path, mime, caption)
            return caption, content
        except Exception as e:
            log.error("Could not read image %s: %s", file_path, e)

    if tm == "documentMessage":
        fname = (archived or {}).get("file_name") or md.get("fileMessageData", {}).get("fileName", "unknown")
        content = f"[Document: {fname}]"
        if caption:
            content += f"\n{caption}"
        return caption, content

    if tm == "videoMessage":
        content = "The user sent a video file. You cannot watch or analyse videos. Politely let them know you can't process video, and suggest they describe what they need help with instead."
        return caption, content

    return caption, caption or f"[{tm}]"


async def dispatch(payload: dict, tw: str, db_pool: asyncpg.Pool, mcp: MCPClientManager):
    if tw not in TRIGGER_TYPES:
        return

    md = payload.get("messageData", {})
    tm = md.get("typeMessage", "")
    is_text = tm in TEXT_TYPES
    is_media = tm in MEDIA_TYPES

    if not is_text and not is_media:
        return

    sd = payload.get("senderData", {})
    chat_id = sd.get("chatId", "")
    sender = sd.get("sender", chat_id)
    is_group = chat_id.endswith("@g.us")

    if tm == "quotedMessage":
        trigger_text, content = await _extract_quoted_content(payload, db_pool)
    elif is_text:
        content = _extract_simple_text(payload)
        if not content:
            return
        trigger_text = content
    else:
        trigger_text, content = await _build_media_content(payload, db_pool)

    # Group chats require trigger in caption/text; personal chats always respond
    matched_trigger = next((t for t in TRIGGERS if t.lower() in trigger_text.lower()), None)
    if is_group and not matched_trigger:
        return

    # Strip the trigger so Claude doesn't see the phone number/name
    if is_group and matched_trigger:
        if isinstance(content, str):
            content = content.replace(matched_trigger, "").strip()
        trigger_text = trigger_text.replace(matched_trigger, "").strip()

    sm = SessionManager(db_pool)

    # Resume a parked session if this sender is being watched
    watcher = await sm.find_watcher(sender, chat_id)
    if watcher:
        session = await sm.load_session(str(watcher["session_id"]))
        if session:
            await sm.delete_watcher(str(watcher["watcher_id"]))
            log.info("resuming session %s for watcher %s", session["session_id"], sender)
            await run_agent_loop(session, f"[Reply from {sender}]: {trigger_text}", sm, mcp)
            return

    log.info("assistant triggered in chat %s (group=%s, type=%s)", chat_id, is_group, tm)
    session = await sm.create_session(chat_id, trigger_text or tm)
    await run_agent_loop(session, content, sm, mcp)
