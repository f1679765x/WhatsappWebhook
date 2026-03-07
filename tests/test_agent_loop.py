import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _session(session_id="s-1", chat_id="65123@c.us", history=None):
    return {
        "session_id": session_id,
        "chat_id": chat_id,
        "conversation_history": history or [],
    }


def _mock_response(stop_reason, content_blocks):
    response = MagicMock()
    response.stop_reason = stop_reason
    blocks = []
    for b in content_blocks:
        block = MagicMock()
        block.model_dump.return_value = b
        blocks.append(block)
    response.content = blocks
    return response


@pytest.mark.asyncio
async def test_end_turn_sends_reply_and_completes():
    from personal_assistant_app.agent_loop import run_agent_loop

    mock_sm = AsyncMock()
    mock_mcp = MagicMock()
    mock_mcp.get_tools.return_value = []

    response = _mock_response("end_turn", [{"type": "text", "text": "Done!"}])

    with patch("personal_assistant_app.agent_loop.anthropic.AsyncAnthropic") as mock_cls, \
         patch("personal_assistant_app.agent_loop.send_message") as mock_send:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = response

        await run_agent_loop(_session(), "hello", mock_sm, mock_mcp)

        mock_send.assert_called_once_with("65123@c.us", "Done!")
        mock_sm.complete_session.assert_called_once_with("s-1")


@pytest.mark.asyncio
async def test_tool_use_calls_mcp_and_continues():
    from personal_assistant_app.agent_loop import run_agent_loop

    mock_sm = AsyncMock()
    mock_mcp = AsyncMock()
    mock_mcp.get_tools.return_value = [{"name": "calendar__listEvents", "description": "", "input_schema": {}}]
    mock_mcp.call_tool.return_value = "event list"

    tool_use_block = {"type": "tool_use", "id": "tu-1", "name": "calendar__listEvents", "input": {}}
    text_block = {"type": "text", "text": "Here are your events"}

    response_1 = _mock_response("tool_use", [tool_use_block])
    response_2 = _mock_response("end_turn", [text_block])

    with patch("personal_assistant_app.agent_loop.anthropic.AsyncAnthropic") as mock_cls, \
         patch("personal_assistant_app.agent_loop.send_message") as mock_send:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = [response_1, response_2]

        await run_agent_loop(_session(), "show my events", mock_sm, mock_mcp)

        mock_mcp.call_tool.assert_called_once_with("calendar__listEvents", {})
        mock_send.assert_called_once_with("65123@c.us", "Here are your events")


@pytest.mark.asyncio
async def test_external_wa_send_registers_watcher():
    from personal_assistant_app.agent_loop import run_agent_loop

    mock_sm = AsyncMock()
    mock_mcp = AsyncMock()
    mock_mcp.get_tools.return_value = []
    mock_mcp.call_tool.return_value = "sent"

    tool_use_block = {
        "type": "tool_use",
        "id": "tu-2",
        "name": "whatsapp__sendMessage",
        "input": {"chatId": "venny@c.us", "message": "Are you free?"},
    }
    response = _mock_response("tool_use", [tool_use_block])

    with patch("personal_assistant_app.agent_loop.anthropic.AsyncAnthropic") as mock_cls, \
         patch("personal_assistant_app.agent_loop.send_message"):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = response

        await run_agent_loop(_session(), "@hardytoo message venny", mock_sm, mock_mcp)

        mock_sm.register_watcher.assert_called_once_with("s-1", "venny@c.us")
        mock_sm.save_session.assert_called()
        last_status = mock_sm.save_session.call_args_list[-1][0][1]
        assert last_status == "waiting_human"


@pytest.mark.asyncio
async def test_claude_api_error_fails_session():
    from personal_assistant_app.agent_loop import run_agent_loop

    mock_sm = AsyncMock()
    mock_mcp = MagicMock()
    mock_mcp.get_tools.return_value = []

    with patch("personal_assistant_app.agent_loop.anthropic.AsyncAnthropic") as mock_cls, \
         patch("personal_assistant_app.agent_loop.send_message") as mock_send:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API error")

        await run_agent_loop(_session(), "hello", mock_sm, mock_mcp)

        mock_sm.fail_session.assert_called_once_with("s-1")
        mock_send.assert_called_once()
