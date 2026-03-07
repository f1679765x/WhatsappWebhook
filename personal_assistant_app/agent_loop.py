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

def _make_db_query_tool(chat_id: str) -> dict:
    return {
        "name": "db_query",
        "description": (
            "Run a read-only SQL SELECT query against the WhatsApp messages database. "
            "Use this to retrieve conversation history, summarise activity, find messages, etc.\n\n"
            "Table: messages\n"
            "Columns:\n"
            "  timestamp_sg  TIMESTAMP  — message time in Singapore time (use this for date filtering)\n"
            "  chat_id       TEXT       — group or personal chat identifier\n"
            "  chat_name     TEXT       — human-readable chat/group name\n"
            "  sender_name   TEXT       — display name of the sender\n"
            "  sender_number TEXT       — sender phone number\n"
            "  type_webhook  TEXT       — incomingMessageReceived | outgoingMessageReceived | outgoingAPIMessageReceived\n"
            "  type_message  TEXT       — textMessage | imageMessage | audioMessage | videoMessage | quotedMessage | documentMessage\n"
            "  text_message  TEXT       — message body (or audio transcript for audioMessage)\n"
            "  caption       TEXT       — caption for media messages\n"
            "  file_name     TEXT       — filename for media\n\n"
            "Rules:\n"
            f"  - ALWAYS filter by chat_id = '{chat_id}' — queries must be scoped to the current chat only\n"
            "  - Only SELECT queries allowed\n"
            "  - Always include LIMIT (max 200)\n"
            "  - Use timestamp_sg for date/time filtering, e.g. timestamp_sg >= NOW() - INTERVAL '2 days'\n"
            "  - Outgoing bot messages have type_webhook = 'outgoingAPIMessageReceived'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A read-only SELECT SQL query"}
            },
            "required": ["sql"],
        },
    }


_BLOCKED_KEYWORDS = {"insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "revoke"}


async def _run_db_query(sql: str, chat_id: str, pool) -> str:
    normalized = sql.strip().lower()
    if not normalized.startswith("select"):
        return "Error: only SELECT queries are allowed."
    for kw in _BLOCKED_KEYWORDS:
        if f" {kw} " in f" {normalized} ":
            return f"Error: keyword '{kw}' is not allowed."
    if chat_id.lower() not in normalized:
        return f"Error: query must be scoped to the current chat. Add WHERE chat_id = '{chat_id}' to your query."
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
        if not rows:
            return "No results found."
        cols = list(rows[0].keys())
        lines = [" | ".join(cols)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join(str(v) if v is not None else "" for v in row.values()))
        return "\n".join(lines)
    except Exception as e:
        return f"Query error: {e}"


READ_URL_TOOL = {
    "name": "read_url",
    "description": (
        "Fetch and read the content of a URL. Use this when the user pastes a link and wants "
        "you to read, summarise, or answer questions about its content."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch"}
        },
        "required": ["url"],
    },
}


async def _read_url(url: str) -> str:
    jina_url = f"https://r.jina.ai/{url}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(jina_url, headers={"Accept": "text/plain"})
        resp.raise_for_status()
    text = resp.text.strip()
    # Truncate to avoid overwhelming the context
    if len(text) > 20000:
        text = text[:20000] + "\n\n[content truncated]"
    return text


END_SESSION_TOOL = {
    "name": "end_session",
    "description": (
        "Call this to explicitly close the conversation when the user's goal is fully met "
        "or when the user indicates they are done (e.g. 'thanks', 'that's all', 'bye'). "
        "After calling this, the bot will stop listening for follow-ups until triggered again."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

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
- Do not hallucinate tool results — if a tool fails, report it honestly
- When the user's goal is fully met or they say they're done (e.g. "thanks", "that's all", "bye"), call end_session to close the conversation"""


def _sanitize_block(block: dict) -> dict:
    """Keep only fields the Anthropic API accepts in stored messages."""
    t = block.get("type")
    if t == "text":
        return {"type": "text", "text": block["text"]}
    if t == "tool_use":
        return {"type": "tool_use", "id": block["id"], "name": block["name"], "input": block["input"]}
    if t == "tool_result":
        return {"type": "tool_result", "tool_use_id": block["tool_use_id"], "content": block.get("content", "")}
    return {k: v for k, v in block.items() if v is not None}


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
    tools = [END_SESSION_TOOL, READ_URL_TOOL, SEARCH_TOOL, _make_db_query_tool(chat_id)] + mcp.get_tools()

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

        assistant_content = [_sanitize_block(block.model_dump()) for block in response.content]
        history.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            text = " ".join(
                b["text"] for b in assistant_content if b.get("type") == "text"
            )
            await send_message(chat_id, text)
            # Keep session as 'thinking' so user can follow up without re-triggering
            await sm.save_session(session_id, "thinking", history)
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

                if tool_name == "read_url":
                    try:
                        result = await _read_url(tool_input.get("url", ""))
                        tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": result})
                    except Exception as e:
                        tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": f"Error fetching URL: {e}", "is_error": True})
                    continue

                if tool_name == "end_session":
                    await sm.complete_session(session_id)
                    log.info("session %s closed by bot", session_id)
                    # Let the loop continue so Claude can send a farewell message
                    tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": "Session closed."})
                    continue

                if tool_name == "web_search":
                    try:
                        result = await _search(tool_input.get("query", ""))
                        tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": result})
                    except Exception as e:
                        tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": f"Search error: {e}", "is_error": True})
                    continue

                if tool_name == "db_query":
                    result = await _run_db_query(tool_input.get("sql", ""), chat_id, sm.pool)
                    tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": result})
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
