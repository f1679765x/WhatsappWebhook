# WhatsApp Webhook Service Specification

## Business Requirements

- Listening on Green API webhook to insert WhatsApp chat messages into PostgreSQL
- If an audio file is received - transcribe the message and store the audio file locally
- If a video or image is received - download and store the file locally
- Store the location of the files relative to D:\WhatsappData
- File naming: yyyy_mm_dd_chatid_filetype_filename (e.g. 2026_12_12_6594760227@c.us_audio_filename1.mp3)
- If the webhook is about deletion of a message, delete the entry and file from the database/file storage

See hardytooSpec.md for the personal assistant agent that is built on top of this service.

## Technical Stack

- Python 3.11, FastAPI, uvicorn
- psycopg2 for PostgreSQL (archive path)
- asyncpg for PostgreSQL (agent path — see hardytooSpec.md)
- httpx for media downloads
- faster-whisper (base model) for audio transcription
- Conda environment: whatsappwebhook
- start.bat / start_service.bat to launch the server

## Webhook Handling

Green API sends webhooks via n8n forwarding. n8n wraps the payload as `{"rawjson": "<json string>"}` — the server unwraps this on receipt.

The webhook endpoint must return `200 OK` immediately. All processing (archiving, agent dispatch) runs in FastAPI background tasks.

### Stored webhook types
- incomingMessageReceived
- outgoingMessageReceived
- outgoingAPIMessageReceived

### Ignored webhook types (200 OK, no storage)
- outgoingMessageStatus
- deviceInfo
- stateInstanceChanged
- incomingCall
- outgoingCall

### Deletion handling
- typeWebhook: messageDeleted — uses idMessage to find and delete the row
- typeMessage: deletedMessage (inside incomingMessageReceived) — uses messageData.deletedMessageData.stanzaId to find and delete the row

### Message types handled
- textMessage, extendedTextMessage, quotedMessage
- imageMessage, videoMessage, audioMessage, documentMessage, stickerMessage
- locationMessage, contactMessage, pollMessage, reactionMessage, listMessage, buttonsMessage

## Database

Docker container: postgres (postgres:17)
- Host: localhost:5432
- DB: whatsapp
- User/Pass: n8n / n8n
- psycopg2 connection string: host=localhost port=5432 dbname=whatsapp user=n8n password=n8n
- asyncpg DATABASE_URL: postgresql://n8n:n8n@localhost:5432/whatsapp

### Schema notes
- id = idMessage (primary key), ON CONFLICT DO NOTHING
- timestamp_utc: TIMESTAMPTZ (UTC)
- timestamp_sg: TIMESTAMP (naive, Singapore time SGT UTC+8)
- file_path: filename only, relative to D:\WhatsappData

### messages table
```sql
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    type_webhook TEXT,
    timestamp BIGINT NOT NULL,
    timestamp_utc TIMESTAMPTZ,
    timestamp_sg  TIMESTAMP,
    id_message TEXT,
    quoted_message_id TEXT,
    chat_id   TEXT,
    chat_name TEXT,
    sender_number TEXT,
    sender_name   TEXT,
    recipient_number TEXT,
    recipient_name   TEXT,
    type_message TEXT,
    text_message TEXT,
    caption      TEXT,
    file_path TEXT,
    file_name TEXT,
    file_mime TEXT,
    raw_json JSONB
);
```

See hardytooSpec.md for the sessions and session_watchers tables.

## Media Storage

- Location: D:\WhatsappData\
- Filename format: yyyy_mm_dd_chatid_filetype_originalname
- On deletion: file removed from disk, row removed from DB

## Environment Variables

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=whatsapp
DB_USER=n8n
DB_PASSWORD=n8n
DATABASE_URL=postgresql://n8n:n8n@localhost:5432/whatsapp
DATA_DIR=D:\WhatsappData
PORT=8000
```

Agent-specific env vars are listed in hardytooSpec.md.
