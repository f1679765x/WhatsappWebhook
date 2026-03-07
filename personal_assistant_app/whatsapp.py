import logging
import os

import httpx

log = logging.getLogger(__name__)

GREEN_API_BASE = "https://api.green-api.com"


async def send_message(chat_id: str, message: str):
    instance_id = os.environ["GREEN_API_INSTANCE_ID"]
    token = os.environ["GREEN_API_TOKEN"]
    url = f"{GREEN_API_BASE}/waInstance{instance_id}/sendMessage/{token}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json={"chatId": chat_id, "message": message})
        resp.raise_for_status()
    log.info("sent WhatsApp message to %s", chat_id)
