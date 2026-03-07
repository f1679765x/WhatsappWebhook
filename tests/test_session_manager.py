import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


def _mock_pool(fetchrow_return=None, execute_return=None):
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = fetchrow_return
    mock_conn.execute.return_value = execute_return
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool, mock_conn


@pytest.mark.asyncio
async def test_create_session():
    from personal_assistant_app.session_manager import SessionManager

    session_row = {
        "session_id": "abc",
        "chat_id": "65123@c.us",
        "status": "thinking",
        "goal": "help me",
        "conversation_history": [],
        "created_at": datetime.now(timezone.utc),
        "last_active_at": datetime.now(timezone.utc),
        "completed_at": None,
    }
    pool, conn = _mock_pool(fetchrow_return=session_row)
    sm = SessionManager(pool)

    result = await sm.create_session("65123@c.us", "help me")

    conn.execute.assert_called_once()
    assert result["chat_id"] == "65123@c.us"


@pytest.mark.asyncio
async def test_save_session():
    from personal_assistant_app.session_manager import SessionManager

    pool, conn = _mock_pool()
    sm = SessionManager(pool)
    history = [{"role": "user", "content": "hello"}]

    await sm.save_session("s-1", "thinking", history)

    conn.execute.assert_called_once()
    args = conn.execute.call_args[0]
    assert args[1] == "thinking"
    assert json.loads(args[2]) == history


@pytest.mark.asyncio
async def test_find_watcher_returns_none():
    from personal_assistant_app.session_manager import SessionManager

    pool, conn = _mock_pool(fetchrow_return=None)
    sm = SessionManager(pool)

    result = await sm.find_watcher("someone@c.us", "chat@c.us")
    assert result is None


@pytest.mark.asyncio
async def test_register_and_delete_watcher():
    from personal_assistant_app.session_manager import SessionManager

    pool, conn = _mock_pool()
    sm = SessionManager(pool)

    watcher_id = await sm.register_watcher("s-1", "venny@c.us", "group@g.us")
    assert watcher_id is not None
    conn.execute.assert_called_once()

    await sm.delete_watcher(watcher_id)
    assert conn.execute.call_count == 2
