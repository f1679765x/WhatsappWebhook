# WhatsApp AI Assistant

A WhatsApp-based AI assistant that takes incoming text or voice messages, runs them through Claude with web-search and persistent memory via MCP tools, and replies — vibe-coded end-to-end with Claude Code.

## What it does

- Receives incoming WhatsApp messages through a FastAPI webhook
- Transcribes voice notes with `faster-whisper`
- Routes the conversation through Claude via the Anthropic SDK
- Gives the assistant agentic tool access via MCP (Model Context Protocol), including web search through Tavily and DuckDuckGo
- Stores conversation history in PostgreSQL for cross-session memory

## Stack

- **Web framework:** FastAPI + Uvicorn
- **LLM:** Anthropic SDK (Claude)
- **Agent tools:** MCP, Tavily, DuckDuckGo
- **Voice transcription:** faster-whisper
- **Database:** PostgreSQL (asyncpg)
- **Testing:** pytest, pytest-asyncio, pytest-cov

## Project structure

```
.
├── listener_app/            # FastAPI webhook to receive WhatsApp messages
├── whatsapp_assistant_app/  # AI assistant logic and MCP tool wiring
├── Instructions/            # System prompts and assistant behavior
├── tests/                   # Test suite
├── mcp_config.json          # MCP server configuration
├── requirements.txt
└── .claude/                 # Claude Code configuration
```

## Setup

1. Clone the repo.
2. Install dependencies: `pip install -r requirements.txt`
3. Create a `.env` file with the required credentials (WhatsApp Business API token, Anthropic API key, Postgres connection string, Tavily API key, etc.).
4. Run the service via `start.bat` (Windows) or launch the FastAPI app directly.

## Tests

```bash
pytest
```

## About this project

This was built end-to-end with Claude Code as the development driver — see `.claude/` and `Instructions/` for the configuration that orchestrated it. The project doubles as a personal AI assistant and a working example of vibe-coding a non-trivial agentic system on real infrastructure.
