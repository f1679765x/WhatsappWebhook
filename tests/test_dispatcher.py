import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _payload(tw, type_message, text, sender="65123@c.us", chat_id="65123@c.us"):
    md = {}
    if type_message == "textMessage":
        md = {"typeMessage": "textMessage", "textMessageData": {"textMessage": text}}
    return {
        "typeWebhook": tw,
        "senderData": {"chatId": chat_id, "sender": sender},
        "messageData": md,
    }


@pytest.mark.asyncio
async def test_ignores_outgoing():
    from personal_assistant_app.dispatcher import dispatch

    mock_pool = MagicMock()
    mock_mcp = MagicMock()
    with patch("personal_assistant_app.dispatcher.SessionManager") as mock_sm_cls:
        await dispatch(_payload("outgoingMessageReceived", "textMessage", "@hardytoo help"), "outgoingMessageReceived", mock_pool, mock_mcp)
        mock_sm_cls.assert_not_called()


@pytest.mark.asyncio
async def test_ignores_non_text_message():
    from personal_assistant_app.dispatcher import dispatch

    payload = {
        "typeWebhook": "incomingMessageReceived",
        "senderData": {"chatId": "65123@c.us", "sender": "65123@c.us"},
        "messageData": {"typeMessage": "imageMessage"},
    }
    with patch("personal_assistant_app.dispatcher.SessionManager") as mock_sm_cls:
        await dispatch(payload, "incomingMessageReceived", MagicMock(), MagicMock())
        mock_sm_cls.assert_not_called()


@pytest.mark.asyncio
async def test_no_trigger_no_watcher_does_nothing():
    from personal_assistant_app.dispatcher import dispatch

    with patch("personal_assistant_app.dispatcher.SessionManager") as mock_sm_cls:
        mock_sm = AsyncMock()
        mock_sm_cls.return_value = mock_sm
        mock_sm.find_watcher.return_value = None

        await dispatch(
            _payload("incomingMessageReceived", "textMessage", "just a normal message"),
            "incomingMessageReceived", MagicMock(), MagicMock(),
        )
        mock_sm.create_session.assert_not_called()


@pytest.mark.asyncio
async def test_hardytoo_trigger_creates_session():
    from personal_assistant_app.dispatcher import dispatch

    with patch("personal_assistant_app.dispatcher.SessionManager") as mock_sm_cls, \
         patch("personal_assistant_app.dispatcher.run_agent_loop") as mock_loop:
        mock_sm = AsyncMock()
        mock_sm_cls.return_value = mock_sm
        mock_sm.find_watcher.return_value = None
        mock_sm.create_session.return_value = {
            "session_id": "abc-123",
            "chat_id": "65123@c.us",
            "conversation_history": [],
        }

        await dispatch(
            _payload("incomingMessageReceived", "textMessage", "@hardytoo book a meeting"),
            "incomingMessageReceived", MagicMock(), MagicMock(),
        )
        mock_sm.create_session.assert_called_once_with("65123@c.us", "@hardytoo book a meeting")
        mock_loop.assert_called_once()


@pytest.mark.asyncio
async def test_watcher_resumes_session():
    from personal_assistant_app.dispatcher import dispatch

    with patch("personal_assistant_app.dispatcher.SessionManager") as mock_sm_cls, \
         patch("personal_assistant_app.dispatcher.run_agent_loop") as mock_loop:
        mock_sm = AsyncMock()
        mock_sm_cls.return_value = mock_sm
        mock_sm.find_watcher.return_value = {
            "watcher_id": "w-1",
            "session_id": "s-1",
        }
        mock_sm.load_session.return_value = {
            "session_id": "s-1",
            "chat_id": "group@g.us",
            "conversation_history": [],
        }

        await dispatch(
            _payload("incomingMessageReceived", "textMessage", "Tuesday works for me", sender="venny@c.us"),
            "incomingMessageReceived", MagicMock(), MagicMock(),
        )
        mock_sm.delete_watcher.assert_called_once_with("w-1")
        mock_loop.assert_called_once()
        call_args = mock_loop.call_args[0]
        assert "[Reply from venny@c.us]" in call_args[1]
