import logging
import os

import anthropic

from personal_assistant_app.mcp_client import MCPClientManager
from personal_assistant_app.session_manager import SessionManager
from personal_assistant_app.whatsapp import send_message

log = logging.getLogger(__name__)

MAX_ITERATIONS = int(os.environ.get("MAX_LOOP_ITERATIONS", 20))
TRIGGERS = [t.strip() for t in os.environ.get("HARDYTOO_TRIGGER", "@hardytoo").split(",")]

SYSTEM_PROMPT = """You are Hardy's personal WhatsApp assistant.
- Be respectful and professional at all times
- Speak in a warm, conversational style — natural and friendly, not stiff or formal
- Be concise — this is WhatsApp, not email or a document
- Formatting rules (WhatsApp only):
  - Use *text* for bold (single asterisk), _text_ for italic — sparingly
  - Never use markdown headers (#, ##), bullet points with -, or double asterisks **
  - Prefer plain prose over lists; only use numbered lists when order truly matters
  - No code blocks unless specifically asked for code
- Default timezone: Asia/Singapore
- Only perform actions available via the tools provided. Do not pretend to have capabilities not backed by a tool.
- Do not hallucinate tool results — if a tool fails, report it honestly"""


async def run_agent_loop(
    session: dict,
    new_message: str | list,
    sm: SessionManager,
    mcp: MCPClientManager,
):
    session_id = session["session_id"]
    chat_id = session["chat_id"]
    history = list(session["conversation_history"] or [])

    history.append({"role": "user", "content": new_message})
    await sm.save_session(session_id, "thinking", history)

    client = anthropic.AsyncAnthropic()
    tools = mcp.get_tools()

    for _ in range(MAX_ITERATIONS):
        try:
            response = await client.messages.create(
                model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=tools or anthropic.NOT_GIVEN,
                messages=history,
            )
        except Exception as e:
            log.error("Claude API error: %s", e)
            await sm.fail_session(session_id)
            await send_message(chat_id, f"Sorry, I hit an error: {e}")
            return

        assistant_content = [block.model_dump() for block in response.content]
        history.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            text = " ".join(
                b["text"] for b in assistant_content if b.get("type") == "text"
            )
            await send_message(chat_id, text)
            await sm.save_session(session_id, "completed", history)
            await sm.complete_session(session_id)
            return

        if response.stop_reason == "tool_use":
            tool_results = []
            external_send = None

            for block in assistant_content:
                if block.get("type") != "tool_use":
                    continue
                tool_name = block["name"]
                tool_input = block["input"]

                if _is_external_wa_send(tool_name, tool_input, chat_id):
                    external_send = (
                        tool_input.get("chatId") or tool_input.get("phone", "")
                    )

                try:
                    result = await mcp.call_tool(tool_name, tool_input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": result,
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": f"Error: {e}",
                        "is_error": True,
                    })

            history.append({"role": "user", "content": tool_results})

            if external_send:
                await sm.register_watcher(session_id, external_send)
                await sm.save_session(session_id, "waiting_human", history)
                return

            await sm.save_session(session_id, "thinking", history)
            continue

    await sm.fail_session(session_id)
    await send_message(chat_id, "I've reached the maximum number of steps. Please try again.")


def _is_external_wa_send(tool_name: str, tool_input: dict, originating_chat: str) -> bool:
    if "whatsapp" not in tool_name.lower() and "send" not in tool_name.lower():
        return False
    recipient = tool_input.get("chatId") or tool_input.get("phone") or ""
    return bool(recipient) and recipient != originating_chat
