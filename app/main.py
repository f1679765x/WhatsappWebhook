import json
import logging

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request

from app.db import delete_message, insert_message
from app.media import DATA_DIR, MEDIA_TYPES, build_filename, delete_file, download_and_save
from app.parser import parse_deleted_id, parse_message
from app.transcription import transcribe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI()

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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    if "rawjson" in payload and "typeWebhook" not in payload:
        raw = payload["rawjson"]
        payload = json.loads(raw) if isinstance(raw, str) else raw
    tw = payload.get("typeWebhook", "")
    log.info("webhook: %s", tw)

    if tw in IGNORED:
        return {"status": "ignored"}

    if tw == "messageDeleted":
        id_msg = parse_deleted_id(payload)
        if id_msg:
            file_path = delete_message(id_msg)
            if file_path:
                delete_file(file_path)
        return {"status": "ok"}

    if tw in MESSAGE_TYPES:
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
                file_path = delete_message(stanza_id)
                if file_path:
                    delete_file(file_path)
            return {"status": "ok"}

        if tm in MEDIA_TYPES_SET and row.get("download_url"):
            fname = build_filename(
                row["chat_id"], tm, row.get("file_name", "file"), row["timestamp"]
            )
            try:
                rel_path = download_and_save(row["download_url"], fname)
                row["file_path"] = rel_path
                row["file_name"] = fname
                if tm == "audioMessage":
                    row["text_message"] = transcribe(str(DATA_DIR / rel_path))
            except Exception as e:
                log.error("media processing failed: %s", e)

        insert_message(row)
        return {"status": "ok"}

    log.warning("unknown webhook type: %s", tw)
    return {"status": "ignored"}
