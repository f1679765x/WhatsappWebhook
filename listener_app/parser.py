from datetime import datetime, timezone, timedelta

SGT = timezone(timedelta(hours=8))

MEDIA_TYPES = {"imageMessage", "videoMessage", "audioMessage", "documentMessage", "stickerMessage"}


def parse_message(payload: dict) -> dict:
    ts = payload.get("timestamp", 0)
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    dt_sg = dt_utc.astimezone(SGT)
    tw = payload.get("typeWebhook", "")
    sd = payload.get("senderData", {})
    md = payload.get("messageData", {})
    tm = md.get("typeMessage", "")
    id_message = payload.get("idMessage", "")

    row = {
        "id": id_message,
        "type_webhook": tw,
        "timestamp": ts,
        "timestamp_utc": dt_utc.isoformat(),
        "timestamp_sg": dt_sg.replace(tzinfo=None).isoformat(),
        "id_message": id_message,
        "quoted_message_id": None,
        "chat_id": sd.get("chatId", ""),
        "chat_name": sd.get("chatName", ""),
        "sender_number": None,
        "sender_name": None,
        "recipient_number": None,
        "recipient_name": None,
        "type_message": tm,
        "text_message": None,
        "caption": None,
        "file_path": None,
        "file_name": None,
        "file_mime": None,
        "raw_json": payload,
        "download_url": None,
    }

    if tw == "incomingMessageReceived":
        row["sender_number"] = sd.get("sender", sd.get("chatId", ""))
        row["sender_name"] = sd.get("senderName", sd.get("senderContactName", ""))
    else:
        row["recipient_number"] = sd.get("chatId", "")
        row["recipient_name"] = sd.get("chatName", "")

    _parse_message_data(row, md, tm)
    return row


def _parse_message_data(row: dict, md: dict, tm: str):
    if tm == "textMessage":
        row["text_message"] = md.get("textMessageData", {}).get("textMessage")

    elif tm in MEDIA_TYPES:
        fd = md.get("fileMessageData", {})
        row["caption"] = fd.get("caption") or None
        row["file_name"] = fd.get("fileName", "")
        row["file_mime"] = fd.get("mimeType", "")
        row["download_url"] = fd.get("downloadUrl", "")

    elif tm == "locationMessage":
        ld = md.get("locationMessageData", {})
        parts = [ld.get("nameLocation", ""), ld.get("address", "")]
        lat, lon = ld.get("latitude"), ld.get("longitude")
        if lat is not None and lon is not None:
            parts.append(f"({lat}, {lon})")
        row["text_message"] = " | ".join(p for p in parts if p) or None

    elif tm == "contactMessage":
        row["text_message"] = md.get("contactMessageData", {}).get("displayName")

    elif tm in ("extendedTextMessage", "quotedMessage"):
        ed = md.get("extendedTextMessageData", {})
        row["text_message"] = ed.get("text")
        row["quoted_message_id"] = ed.get("stanzaId") or None

    elif tm == "pollMessage":
        pd = md.get("pollMessageData", {})
        opts = ", ".join(o.get("optionName", "") for o in pd.get("options", []))
        row["text_message"] = f"{pd.get('name', '')} | {opts}"

    elif tm == "reactionMessage":
        rd = md.get("reactionMessageData", {})
        row["text_message"] = rd.get("reaction")
        row["quoted_message_id"] = rd.get("messageId") or None

    elif tm == "listMessage":
        lm = md.get("listMessage", {})
        row["text_message"] = lm.get("title") or lm.get("description")

    elif tm == "buttonsMessage":
        bm = md.get("buttonsMessage", {})
        row["text_message"] = bm.get("contentText")


def parse_deleted_id(payload: dict) -> str:
    return payload.get("idMessage", "")
