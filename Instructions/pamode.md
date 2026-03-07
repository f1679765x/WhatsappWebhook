# Plan: Hardy's Personal Assistant (PA) Mode

## Context
Hardy wants a privileged "PA mode" that activates only when a direct (non-group) WhatsApp message arrives from his personal number +6594760227. In PA mode, the bot has elevated capabilities: Gmail, Calendar (via MCP), full DB access across all chats, contact management, and the ability to send WhatsApp messages and polls on Hardy's behalf. All other users continue to get the regular bot.

---

## Architecture: How It Works

**Detection:** `is_owner = (sender == "6594760227@c.us") AND (NOT is_group)`
Only direct messages from Hardy's personal number activate PA mode. Group messages from the same number do not.

**Layering:** PA mode = all regular tools + PA-only tools + MCP tools (Gmail/Calendar). Regular users never see MCP tools.

---

## 1. New DB Table: `contacts`

```sql
CREATE TABLE contacts (
    id         SERIAL PRIMARY KEY,
    phone      TEXT NOT NULL,       -- e.g. "6592226590" (no +)
    name       TEXT NOT NULL,       -- e.g. "Venny"
    alias      TEXT,                -- e.g. "wife", "mum"
    notes      TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
-- Seed initial contacts:
INSERT INTO contacts (phone, name, alias) VALUES
    ('6592226590', 'Venny', 'wife');
```

---

## 2. `.env` Addition

```
OWNER_NUMBER=6594760227
```

---

## 3. `whatsapp_assistant_app/dispatcher.py`

- Read `OWNER_NUMBER` from env
- Detect `is_owner = (sender == f"{OWNER_NUMBER}@c.us") and not is_group`
- Pass `is_owner` to `run_agent_loop()`

```python
OWNER_NUMBER = os.environ.get("OWNER_NUMBER", "")
...
is_owner = bool(OWNER_NUMBER) and sender == f"{OWNER_NUMBER}@c.us" and not is_group
...
await run_agent_loop(session, content, sm, mcp, is_owner=is_owner)
```

---

## 4. `whatsapp_assistant_app/agent_loop.py`

### 4a. Add `is_owner` parameter to `run_agent_loop`
```python
async def run_agent_loop(session, new_message, sm, mcp, is_owner=False):
```

### 4b. PA-only system prompt
```python
PA_SYSTEM_PROMPT = """You are Hardy Too, Hardy Hutajaya's personal AI assistant.
You are speaking directly and privately with Hardy.
- Act autonomously and proactively on Hardy's behalf
- You have access to his Gmail, Google Calendar, contacts, and full WhatsApp history
- Always use contact_lookup before sending messages to people referred to by name/relation
- Before sending any WhatsApp message to an external party, confirm the message content with Hardy first
- Speak naturally and personally — you know Hardy well
- Default timezone: Asia/Singapore
- Use WhatsApp formatting only (*bold*, _italic_, no markdown headers)
- Call end_session when the conversation is done"""
```

### 4c. PA-only tools (new async functions + tool definitions)

**`contact_lookup(query, pool)`**
- SELECT from contacts WHERE alias ILIKE query OR name ILIKE query
- Returns phone, name, alias, notes

**`contact_save(phone, name, alias, notes, pool)`**
- INSERT ... ON CONFLICT (phone) DO UPDATE

**`send_whatsapp_message(phone, message)`**
- Calls Green API sendMessage to `{phone}@c.us`

**`send_whatsapp_poll(chat_id, question, options, multiple_answers)`**
- Calls Green API sendPoll endpoint

**Unrestricted `db_query_pa`**
- Same as regular `db_query` but WITHOUT the `chat_id` filter enforcement — can query all chats

### 4d. Tool set assembly
```python
if is_owner:
    tools = [END_SESSION_TOOL, READ_URL_TOOL, SEARCH_TOOL,
             DB_QUERY_PA_TOOL,           # unrestricted
             CONTACT_LOOKUP_TOOL,
             CONTACT_SAVE_TOOL,
             SEND_WA_MESSAGE_TOOL,
             SEND_WA_POLL_TOOL] + mcp.get_tools()   # <- Gmail/Calendar
    system = PA_SYSTEM_PROMPT
else:
    tools = [END_SESSION_TOOL, READ_URL_TOOL, SEARCH_TOOL,
             _make_db_query_tool(chat_id)]           # <- no MCP, scoped DB
    system = SYSTEM_PROMPT
```

### 4e. Tool dispatch (in the tool_use loop)
Add handlers for: `contact_lookup`, `contact_save`, `send_whatsapp_message`, `send_whatsapp_poll`, `db_query_pa`

---

## 5. `mcp_config.json` — Gmail & Calendar MCP Servers

The MCP servers for Gmail and Google Calendar need to be configured here. This requires Hardy to:
1. Set up Google OAuth credentials
2. Choose and install MCP server packages for Gmail and Google Calendar
3. Add their config to `mcp_config.json`

This is a separate setup step — the code will automatically pick up any MCP tools once configured. Recommended servers to research: `@modelcontextprotocol/server-gmail`, `@gptscript-ai/google-workspace-mcp`, or similar community servers.

---

## Files to Modify
| File | Change |
|---|---|
| `.env` | Add `OWNER_NUMBER=6594760227` |
| `whatsapp_assistant_app/dispatcher.py` | Detect `is_owner`, pass to `run_agent_loop` |
| `whatsapp_assistant_app/agent_loop.py` | PA system prompt, PA tools, conditional tool set |
| `mcp_config.json` | Add Gmail + Calendar MCP servers (separate setup step) |
| DB | Create `contacts` table, seed Venny |

---

## Verification
1. Send a message from Hardy's personal number `@6594760227` directly to the bot
2. Confirm logs show `is_owner=True` and PA system prompt is used
3. Ask: "who is my wife?" → bot calls `contact_lookup("wife")` → returns Venny
4. Ask: "text my wife that I'll be late" → bot confirms message → sends via Green API
5. Ask: "summarise all chats from today" → bot runs unrestricted DB query across all chat_ids
6. (After MCP setup) Ask: "what's in my calendar tomorrow?" → bot uses Calendar MCP tool
