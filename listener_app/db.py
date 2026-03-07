import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager


def _connect():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


@contextmanager
def _conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_SQL_INSERT = """
    INSERT INTO messages (
        id, type_webhook, timestamp, timestamp_utc, timestamp_sg,
        id_message, quoted_message_id, chat_id, chat_name,
        sender_number, sender_name, recipient_number, recipient_name,
        type_message, text_message, caption,
        file_path, file_name, file_mime, raw_json
    ) VALUES (
        %(id)s, %(type_webhook)s, %(timestamp)s, %(timestamp_utc)s, %(timestamp_sg)s,
        %(id_message)s, %(quoted_message_id)s, %(chat_id)s, %(chat_name)s,
        %(sender_number)s, %(sender_name)s, %(recipient_number)s, %(recipient_name)s,
        %(type_message)s, %(text_message)s, %(caption)s,
        %(file_path)s, %(file_name)s, %(file_mime)s, %(raw_json)s
    )
    ON CONFLICT (id) DO NOTHING
"""


def insert_message(row: dict):
    r = {k: v for k, v in row.items() if k != "download_url"}
    r["raw_json"] = psycopg2.extras.Json(r.get("raw_json", {}))
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL_INSERT, r)


def delete_message(id_message: str) -> str | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT file_path FROM messages WHERE id_message = %s", (id_message,)
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "DELETE FROM messages WHERE id_message = %s", (id_message,)
                )
                return row[0]
    return None
