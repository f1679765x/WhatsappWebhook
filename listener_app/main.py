import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import asyncpg
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request

load_dotenv()

from listener_app.db import delete_message, insert_message
from listener_app.media import DATA_DIR, MEDIA_TYPES, build_filename, delete_file, download_and_save
from listener_app.parser import parse_deleted_id, parse_message
from listener_app.transcription import transcribe
from whatsapp_assistant_app.dispatcher import dispatch
from whatsapp_assistant_app.mcp_client import MCPClientManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

IGNORED = {
    "outgoingMessageStatus",
    "deviceInfo",
    "stateInstanceChanged",
    "incomingCall",
    "outgoingCall",
}
MESSAGE_TYPES = {
    "incomingMessageReceived",
    "outgoingMessageReceived",
    "outgoingAPIMessageReceived",
}
MEDIA_TYPES_SET = set(MEDIA_TYPES)


async def _init_connection(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"], min_size=2, max_size=10, init=_init_connection
    )
    app.state.mcp = MCPClientManager()
    await app.state.mcp.start()
    yield
    await app.state.db_pool.close()
    await app.state.mcp.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    if "rawjson" in payload and "typeWebhook" not in payload:
        raw = payload["rawjson"]
        payload = json.loads(raw) if isinstance(raw, str) else raw
    tw = payload.get("typeWebhook", "")
    log.info("webhook: %s", tw)
    background_tasks.add_task(
        process_webhook, payload, tw, request.app.state.db_pool, request.app.state.mcp
    )
    return {"status": "ok"}


async def process_webhook(payload: dict, tw: str, db_pool: asyncpg.Pool, mcp: MCPClientManager):
    try:
        await _archive(payload, tw)
        await dispatch(payload, tw, db_pool, mcp)
    except Exception as e:
        log.error("process_webhook error: %s", e, exc_info=True)


async def _archive(payload: dict, tw: str):
    if tw in IGNORED:
        return

    if tw == "messageDeleted":
        id_msg = parse_deleted_id(payload)
        if id_msg:
            file_path = await asyncio.to_thread(delete_message, id_msg)
            if file_path:
                await asyncio.to_thread(delete_file, file_path)
        return

    if tw not in MESSAGE_TYPES:
        return

    row = parse_message(payload)
    tm = row.get("type_message", "")

    if tm == "deletedMessage":
        stanza_id = (
            payload.get("messageData", {})
            .get("deletedMessageData", {})
            .get("stanzaId")
        )
        if stanza_id:
            log.info("deleting message: %s", stanza_id)
            file_path = await asyncio.to_thread(delete_message, stanza_id)
            if file_path:
                await asyncio.to_thread(delete_file, file_path)
        return

    if tm in MEDIA_TYPES_SET and row.get("download_url"):
        rel_path, bare_name = build_filename(
            row["chat_id"], row.get("chat_name", ""), tm, row.get("file_name", "file"), row["timestamp"]
        )
        try:
            rel_path = await asyncio.to_thread(download_and_save, row["download_url"], rel_path)
            row["file_path"] = rel_path
            row["file_name"] = bare_name
            if tm == "audioMessage":
                row["text_message"] = await asyncio.to_thread(
                    transcribe, str(DATA_DIR / rel_path)
                )
        except Exception as e:
            log.error("media processing failed: %s", e)

    await asyncio.to_thread(insert_message, row)
