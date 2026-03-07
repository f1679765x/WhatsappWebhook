import asyncio
import logging
import os

import anthropic
import httpx

from personal_assistant_app.mcp_client import MCPClientManager
from personal_assistant_app.session_manager import SessionManager
from personal_assistant_app.whatsapp import send_message

log = logging.getLogger(__name__)

MAX_ITERATIONS = int(os.environ.get("MAX_LOOP_ITERATIONS", 20))
TRIGGERS = [t.strip() for t in os.environ.get("HARDYTOO_TRIGGER", "@hardytoo").split(",")]

SEARCH_TOOL = {
    "name": "web_search",
    "description": "Search the web for current information, news, prices, or facts beyond your training data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"}
        },
        "required": ["query"],
    },
}


async def _search(query: str) -> str:
    """Try Tavily first; fall back to DuckDuckGo if Tavily fails."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": api_key, "query": query, "max_results": 5},
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
            if results:
                log.info("web search via Tavily: %s", query)
                return "\n\n".join(
                    f"{r['title']}\n{r['url']}\n{r.get('content', '')}" for r in results
                )
        except Exception as e:
            log.warning("Tavily failed (%s), falling back to DuckDuckGo", e)

    # DuckDuckGo fallback
    def _ddg(q: str) -> str:
        from duckduckgo_search import DDGS
        results = list(DDGS().text(q, max_results=5))
        if not results:
            return "No results found."
        return "\n\n".join(
            f"{r['title']}\n{r['href']}\n{r['body']}" for r in results
        )

    log.info("web search via DuckDuckGo: %s", query)
    return await asyncio.to_thread(_ddg, query)

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
    tools = [SEARCH_TOOL] + mcp.get_tools()

    for _ in range(MAX_ITERATIONS):
        try:
            response = await client.messages.create(
                model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=tools,
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

                if tool_name == "web_search":
                    try:
                        result = await _search(tool_input.get("query", ""))
                        tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": result})
                    except Exception as e:
                        tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": f"Search error: {e}", "is_error": True})
                    continue

                # MCP tools (namespaced with __)
                if "__" not in tool_name:
                    continue

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
