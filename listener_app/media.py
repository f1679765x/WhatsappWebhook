import os
import re
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


def _safe_folder(name: str, fallback: str) -> str:
    """Turn a chat name into a safe directory name."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name).strip()
    cleaned = re.sub(r'\s+', " ", cleaned)[:60]
    return cleaned if cleaned else re.sub(r'[^\w-]', "_", fallback)[:40]


def build_filename(chat_id: str, chat_name: str, type_message: str, original_name: str, timestamp: int) -> tuple[str, str]:
    """Returns (relative_path, bare_filename). relative_path includes the chat subfolder."""
    folder = _safe_folder(chat_name, chat_id)
    date_str = datetime.fromtimestamp(timestamp).strftime("%Y_%m_%d")
    filetype = MEDIA_TYPES.get(type_message, type_message)
    name = Path(original_name).name
    bare = f"{date_str}_{filetype}_{name}"
    return f"{folder}/{bare}", bare


def download_and_save(url: str, rel_path: str) -> str:
    dest = DATA_DIR / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return rel_path


def delete_file(filename: str):
    path = DATA_DIR / filename
    if path.exists():
        path.unlink()
