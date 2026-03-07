from unittest.mock import MagicMock, patch

from app.db import delete_message, insert_message


def _make_row():
    return {
        "id": "MSG001",
        "type_webhook": "incomingMessageReceived",
        "timestamp": 1700000000,
        "timestamp_utc": "2023-11-14T22:13:20+00:00",
        "timestamp_sg": "2023-11-15T06:13:20+08:00",
        "id_message": "MSG001",
        "quoted_message_id": None,
        "chat_id": "6594760227@c.us",
        "chat_name": "Test",
        "sender_number": "6594760227@c.us",
        "sender_name": "Test User",
        "recipient_number": None,
        "recipient_name": None,
        "type_message": "textMessage",
        "text_message": "Hello",
        "caption": None,
        "file_path": None,
        "file_name": None,
        "file_mime": None,
        "raw_json": {"key": "value"},
        "download_url": "https://example.com/file",
    }


@patch("app.db._connect")
def test_insert_message_calls_execute(mock_connect):
    mock_conn = MagicMock()
    mock_cur = mock_conn.cursor.return_value.__enter__.return_value
    mock_connect.return_value = mock_conn

    insert_message(_make_row())

    mock_cur.execute.assert_called_once()
    mock_conn.commit.assert_called_once()


@patch("app.db._connect")
def test_insert_strips_download_url(mock_connect):
    mock_conn = MagicMock()
    mock_cur = mock_conn.cursor.return_value.__enter__.return_value
    mock_connect.return_value = mock_conn

    insert_message(_make_row())

    call_args = str(mock_cur.execute.call_args)
    assert "download_url" not in call_args


@patch("app.db._connect")
def test_delete_message_returns_file_path(mock_connect):
    mock_conn = MagicMock()
    mock_cur = mock_conn.cursor.return_value.__enter__.return_value
    mock_cur.fetchone.return_value = ("2023_01_01_chat_audio_file.mp3",)
    mock_connect.return_value = mock_conn

    result = delete_message("MSG001")

    assert result == "2023_01_01_chat_audio_file.mp3"
    assert mock_cur.execute.call_count == 2


@patch("app.db._connect")
def test_delete_message_not_found(mock_connect):
    mock_conn = MagicMock()
    mock_cur = mock_conn.cursor.return_value.__enter__.return_value
    mock_cur.fetchone.return_value = None
    mock_connect.return_value = mock_conn

    result = delete_message("NONEXISTENT")

    assert result is None
    mock_cur.execute.assert_called_once()
