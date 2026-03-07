# WhatsApp Personal Assistant — Architecture & Implementation Plan

## Overview

A Python-based agentic personal assistant triggered by `@hardytoo` mentions in WhatsApp messages. Uses Claude as the reasoning engine, MCP servers for tool access, and a PostgreSQL-backed session state machine to support multi-turn autonomous workflows — including waiting for external replies and resuming mid-task.

---

## Existing Infrastructure (Do Not Rebuild)

- **Green API WhatsApp listener** — already running, fires webhooks on every incoming message
- **PostgreSQL database** — already running, messages are already being archived (text, audio, image, video). See webhookSpec.md for full schema and connection details.
- **Cloudflare Tunnel** — already exposes local services at hardyhutajaya.com
- **n8n** — forwards Green API webhooks to the FastAPI server, wrapping each payload as `{"rawjson": "<json string>"}`. The server already handles unwrapping.

---

## High-Level Architecture

```
Green API Webhook
       │
       ▼
FastAPI Webhook Receiver (returns 200 immediately, dispatches background task)
  ├── Always: archive message (existing behaviour — psycopg2, sync)
  ├── Check: does any active session have a watcher for this sender?
  │     └── YES → resume that session
  └── Check: does message contain @hardytoo?
        └── YES → create new session
               │
               ▼
         Session Manager (PostgreSQL, asyncpg)
               │
               ▼
         Agentic Loop (ReAct: Think → Act → Observe → repeat)
               │
        ┌──────┴──────┐
        ▼             ▼
  MCP Tool Call    Reply via WhatsApp
```

---

## Session State Machine

A session is created for every `@hardytoo` trigger and persists until the task is complete or fails.

### States

| State | Meaning |
|---|---|
| `thinking` | Agent loop is actively running |
| `waiting_human` | Agent sent a message to an external party and is waiting for their reply |
| `completed` | Task finished, final reply sent |
| `failed` | Unrecoverable error |

### State Transitions

```
[created] → thinking
thinking  → waiting_human   (agent sends external WA message, watcher registered)
thinking  → completed       (agent reaches end_turn with no pending actions)
thinking  → failed          (exception or max iterations reached)
waiting_human → thinking    (watcher fires: external reply received)
```

---

## Database Tables Required

Same PostgreSQL instance as the webhook service (postgres:17, DB: whatsapp, user/pass: n8n/n8n).
Agent code uses asyncpg; archive code continues using psycopg2.

### sessions
Tracks every active or historical PA task.

| Column | Type | Notes |
|---|---|---|
| session_id | UUID PK | |
| chat_id | TEXT | The WhatsApp chat/group where @hardytoo was triggered |
| status | TEXT | See state machine above |
| goal | TEXT | The original user request |
| conversation_history | JSONB | Full message history for the LLM, including tool calls and results |
| created_at | TIMESTAMPTZ | |
| last_active_at | TIMESTAMPTZ | Updated on every turn |
| completed_at | TIMESTAMPTZ | Nullable |

### session_watchers
Registers which external contact/chat should wake a parked session.

| Column | Type | Notes |
|---|---|---|
| watcher_id | UUID PK | |
| session_id | UUID FK → sessions | |
| watch_contact | TEXT | WhatsApp number/contact ID to watch for |
| watch_chat_id | TEXT | Optional — scope watcher to a specific chat |
| created_at | TIMESTAMPTZ | |

---

## Core Modules

### 1. Webhook Receiver
- FastAPI endpoint at `POST /webhook`
- Must return `200 OK` immediately — all processing runs async in background tasks
- Calls the dispatcher in a non-blocking way

### 2. Dispatcher
Routing logic executed on every incoming message:
1. Archive the message (delegate to existing archive logic)
2. Query `session_watchers` — does any active session watch this sender?
   - If yes: load that session, append the reply to its conversation history, set status to `thinking`, re-run agent loop
3. Check if message contains `@hardytoo`
   - If yes: create a new session, run agent loop
4. Otherwise: do nothing further

### 3. Session Manager
CRUD layer over the sessions and session_watchers tables:
- Create session from trigger message
- Load session by ID
- Save session state + history after every turn
- Find watcher by sender contact + chat
- Register watcher when agent sends an external message
- Delete watcher once it fires

### 4. Agentic Loop
ReAct-style loop using the Anthropic Python SDK with tool use:

1. Build tool list from all connected MCP servers
2. Call Claude with full conversation history + available tools
3. If `stop_reason == tool_use`:
   - For each tool call: dispatch to the correct MCP server, get result, append to history
   - Special case: if the tool call is a WhatsApp send to an external party → register watcher, set session to `waiting_human`, break loop
4. If `stop_reason == end_turn`:
   - Extract text response, send back to originating chat
   - Set session to `completed`
5. Persist session after every iteration
6. Enforce a max iteration limit (e.g. 20 turns) to prevent runaway loops

### 5. MCP Client Manager
- Manages persistent connections to all configured MCP servers
- Exposes a unified tool list in Anthropic tool format
- Namespaces all tool names by server to avoid collisions: `servername__toolname`
- Routes tool calls back to the correct server based on the namespace prefix
- Handles reconnection on failure

### 6. Tool Dispatcher
- Receives a namespaced tool name + input from the agent loop
- Strips namespace prefix, routes to correct MCP client
- Contains helper logic to detect "external WhatsApp send" calls (so the agent loop knows when to register a watcher)

---

## MCP Servers

### Initial Set

| MCP Server | Purpose |
|---|---|
| WhatsApp (Green API) | Send messages to any contact |
| Google Calendar | Read free/busy slots, create events |
| PostgreSQL | Query archived message history for context |
| Gmail | Secondary messaging channel, send summaries |
| Web Search (Brave) | Look up information on demand |
| Fetch | Retrieve and read a URL pasted into chat |
| Time/Timezone | Convert times across SG / Saudi / Indonesia |

### Add Later
Google Drive, Notion, GitHub

---

## Agentic Loop — Critical Behaviours

**Watcher registration:** When the agent calls a WhatsApp send tool targeting a contact that is NOT the session's originating chat (i.e. an external party), the loop must register a watcher for that contact, set session to `waiting_human`, and break immediately — do not continue iterating.

**Session resume:** When a watcher fires, the incoming message is appended to conversation history as a user turn with a clear label (e.g. `[Reply from Venny]: ...`), then the loop re-enters from the current state.

**History persistence:** Conversation history must be saved to PostgreSQL after every turn, not just at completion. Sessions must survive server restarts.

**Max iterations:** Hard cap (e.g. 20 turns) per session activation. If hit, send a failure message to the originating chat and mark session as `failed`.

**Context scoping:** When querying message history via PostgreSQL MCP, the agent must only retrieve messages from the originating chat. It must not have visibility into other chats.

---

## System Prompt Guidance

The system prompt given to Claude in the agentic loop should convey:
- It is Hardy's personal assistant operating via WhatsApp
- Be concise — WhatsApp format, not email
- Default timezone: Asia/Singapore
- Always confirm before irreversible actions (sending messages to third parties, creating calendar events)
- When messaging an external party, clearly report back to Hardy's chat what it has done and what it is waiting for
- Do not hallucinate tool results — if a tool fails, report it honestly

---

## Example Flow — Scheduling a Meeting

**Trigger:** `@hardytoo find a time to meet with Venny this week`

1. Dispatcher creates session, agent loop starts
2. Agent calls calendar tool → retrieves Hardy's free slots this week
3. Agent calls WhatsApp send → messages Venny with options
4. Watcher registered for Venny; session parked as `waiting_human`
5. Agent replies to originating chat confirming it has messaged Venny
6. Venny replies → watcher fires → session resumes
7. Agent calls calendar create → books the agreed slot
8. Agent replies to originating chat confirming event is in the calendar
9. Session marked `completed`

---

## Environment Variables Required

```
ANTHROPIC_API_KEY=
GREEN_API_INSTANCE_ID=
GREEN_API_TOKEN=
DATABASE_URL=postgresql://n8n:n8n@localhost:5432/whatsapp
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=
BRAVE_SEARCH_API_KEY=
HARDYTOO_TRIGGER=@hardytoo
MAX_LOOP_ITERATIONS=20
PORT=8000
```

Webhook service env vars (DB_HOST, DB_NAME, etc.) are listed in webhookSpec.md and remain unchanged.

---

## Build Order

| Phase | Deliverable |
|---|---|
| 1 | FastAPI webhook receiver wired into existing archive logic, returns 200 immediately via background tasks |
| 2 | Sessions + watchers DB tables and session manager CRUD |
| 3 | Basic agentic loop with Calendar MCP only — prove end-to-end flow works |
| 4 | WhatsApp MCP send + watcher registration |
| 5 | Watcher detection and session resume — most critical piece, validate thoroughly |
| 6 | Remaining MCPs added one by one |

---

## Key Risks & Constraints

- **Green API webhook timeout:** Must return `200` in under 5 seconds or Green API will retry, causing duplicate sessions. All processing must be non-blocking.
- **Watcher false positives:** A contact might send an unrelated message that wakes a session. The agent should detect this and re-park or ask Hardy for clarification.
- **Concurrent sessions:** Multiple `@hardytoo` triggers in the same chat could create parallel sessions. Decide upfront: queue them, reject duplicates, or allow parallel.
- **MCP server restarts:** MCP connections are long-lived. The client manager must handle reconnection gracefully without losing in-flight sessions.
- **Context window growth:** Long-running sessions accumulate large histories. Consider summarising old turns once history exceeds a token threshold.
