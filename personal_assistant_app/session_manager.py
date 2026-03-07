import json
import logging
import uuid
from datetime import datetime, timezone

import asyncpg

log = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create_session(self, chat_id: str, goal: str) -> dict:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sessions
                    (session_id, chat_id, status, goal, conversation_history, created_at, last_active_at)
                VALUES ($1, $2, 'thinking', $3, '[]'::jsonb, $4, $4)
                """,
                session_id, chat_id, goal, now,
            )
        return await self.load_session(session_id)

    async def load_session(self, session_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sessions WHERE session_id = $1", session_id
            )
        return dict(row) if row else None

    async def save_session(self, session_id: str, status: str, history: list):
        now = datetime.now(timezone.utc)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sessions
                SET status = $1, conversation_history = $2::jsonb, last_active_at = $3
                WHERE session_id = $4
                """,
                status, json.dumps(history), now, session_id,
            )

    async def complete_session(self, session_id: str):
        now = datetime.now(timezone.utc)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sessions
                SET status = 'completed', last_active_at = $1, completed_at = $1
                WHERE session_id = $2
                """,
                now, session_id,
            )

    async def fail_session(self, session_id: str):
        now = datetime.now(timezone.utc)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sessions SET status = 'failed', last_active_at = $1
                WHERE session_id = $2
                """,
                now, session_id,
            )

    async def register_watcher(self, session_id: str, watch_contact: str, watch_chat_id: str = None):
        watcher_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO session_watchers
                    (watcher_id, session_id, watch_contact, watch_chat_id, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                watcher_id, session_id, watch_contact, watch_chat_id, now,
            )
        return watcher_id

    async def find_watcher(self, sender: str, chat_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT w.* FROM session_watchers w
                JOIN sessions s ON s.session_id = w.session_id
                WHERE s.status = 'waiting_human'
                  AND w.watch_contact = $1
                  AND (w.watch_chat_id IS NULL OR w.watch_chat_id = $2)
                ORDER BY w.created_at
                LIMIT 1
                """,
                sender, chat_id,
            )
        return dict(row) if row else None

    async def delete_watcher(self, watcher_id: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM session_watchers WHERE watcher_id = $1", watcher_id
            )
