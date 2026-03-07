import os
from datetime import datetime
from pathlib import Path

import httpx

DATA_DIR = Path(os.environ.get("DATA_DIR", r"D:\WhatsappData"))

MEDIA_TYPES = {
    "imageMessage": "image",
    "videoMessage": "video",
    "audioMessage": "audio",
    "documentMessage": "document",
    "stickerMessage": "sticker",
}


def build_filename(chat_id: str, type_message: str, original_name: str, timestamp: int) -> str:
    date_str = datetime.fromtimestamp(timestamp).strftime("%Y_%m_%d")
    filetype = MEDIA_TYPES.get(type_message, type_message)
    name = Path(original_name).name
    return f"{date_str}_{chat_id}_{filetype}_{name}"


def download_and_save(url: str, filename: str) -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / filename
    with httpx.Client(timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return filename


def delete_file(filename: str):
    path = DATA_DIR / filename
    if path.exists():
        path.unlink()
