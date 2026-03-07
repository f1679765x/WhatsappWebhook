from app.parser import parse_deleted_id, parse_message


def _payload(type_webhook, id_message, type_message, message_data, sender_data=None):
    sd = sender_data or {
        "chatId": "6594760227@c.us",
        "chatName": "Test Chat",
        "sender": "6594760227@c.us",
        "senderName": "Test User",
    }
    return {
        "typeWebhook": type_webhook,
        "timestamp": 1700000000,
        "idMessage": id_message,
        "senderData": sd,
        "messageData": {"typeMessage": type_message, **message_data},
    }


def test_text_message_incoming():
    row = parse_message(
        _payload(
            "incomingMessageReceived",
            "MSG001",
            "textMessage",
            {"textMessageData": {"textMessage": "Hello"}},
        )
    )
    assert row["id"] == "MSG001"
    assert row["id_message"] == "MSG001"
    assert row["text_message"] == "Hello"
    assert row["type_message"] == "textMessage"
    assert row["sender_number"] == "6594760227@c.us"
    assert row["recipient_number"] is None


def test_outgoing_message():
    row = parse_message(
        _payload(
            "outgoingAPIMessageReceived",
            "MSG002",
            "textMessage",
            {"textMessageData": {"textMessage": "Hi"}},
            sender_data={"chatId": "6594760227@c.us", "chatName": "Test"},
        )
    )
    assert row["recipient_number"] == "6594760227@c.us"
    assert row["sender_number"] is None


def test_audio_message():
    row = parse_message(
        _payload(
            "incomingMessageReceived",
            "MSG003",
            "audioMessage",
            {
                "fileMessageData": {
                    "downloadUrl": "https://example.com/audio.ogg",
                    "fileName": "audio.ogg",
                    "mimeType": "audio/ogg",
                    "caption": "",
                }
            },
        )
    )
    assert row["download_url"] == "https://example.com/audio.ogg"
    assert row["file_name"] == "audio.ogg"
    assert row["file_mime"] == "audio/ogg"
    assert row["caption"] is None


def test_image_message_with_caption():
    row = parse_message(
        _payload(
            "incomingMessageReceived",
            "MSG004",
            "imageMessage",
            {
                "fileMessageData": {
                    "downloadUrl": "https://example.com/img.jpg",
                    "fileName": "img.jpg",
                    "mimeType": "image/jpeg",
                    "caption": "A photo",
                }
            },
        )
    )
    assert row["caption"] == "A photo"
    assert row["type_message"] == "imageMessage"


def test_location_message():
    row = parse_message(
        _payload(
            "incomingMessageReceived",
            "MSG005",
            "locationMessage",
            {
                "locationMessageData": {
                    "nameLocation": "Home",
                    "address": "123 Main St",
                    "latitude": 1.3521,
                    "longitude": 103.8198,
                }
            },
        )
    )
    assert "Home" in row["text_message"]
    assert "1.3521" in row["text_message"]
    assert "103.8198" in row["text_message"]


def test_contact_message():
    row = parse_message(
        _payload(
            "incomingMessageReceived",
            "MSG006",
            "contactMessage",
            {"contactMessageData": {"displayName": "John Doe", "vcard": "BEGIN:VCARD"}},
        )
    )
    assert row["text_message"] == "John Doe"


def test_quoted_message():
    row = parse_message(
        _payload(
            "incomingMessageReceived",
            "MSG007",
            "quotedMessage",
            {
                "extendedTextMessageData": {
                    "text": "Reply text",
                    "stanzaId": "ORIGINAL001",
                    "participant": "6594760227@c.us",
                }
            },
        )
    )
    assert row["text_message"] == "Reply text"
    assert row["quoted_message_id"] == "ORIGINAL001"


def test_reaction_message():
    row = parse_message(
        _payload(
            "incomingMessageReceived",
            "MSG008",
            "reactionMessage",
            {
                "reactionMessageData": {
                    "messageId": "ORIGINAL002",
                    "reaction": "👍",
                    "participant": "6594760227@c.us",
                }
            },
        )
    )
    assert row["text_message"] == "👍"
    assert row["quoted_message_id"] == "ORIGINAL002"


def test_poll_message():
    row = parse_message(
        _payload(
            "incomingMessageReceived",
            "MSG009",
            "pollMessage",
            {
                "pollMessageData": {
                    "name": "Favorite color?",
                    "options": [{"optionName": "Red"}, {"optionName": "Blue"}],
                    "multipleAnswers": False,
                }
            },
        )
    )
    assert "Favorite color?" in row["text_message"]
    assert "Red" in row["text_message"]
    assert "Blue" in row["text_message"]


def test_timestamps():
    row = parse_message(
        _payload(
            "incomingMessageReceived",
            "MSG010",
            "textMessage",
            {"textMessageData": {"textMessage": "ts"}},
        )
    )
    assert row["timestamp"] == 1700000000
    assert row["timestamp_utc"] is not None
    assert row["timestamp_sg"] is not None
    assert "+08:00" not in row["timestamp_sg"]  # naive SGT, no tz offset
    assert "2023-11-15T06:13:20" == row["timestamp_sg"]  # 1700000000 UTC = 06:13:20 SGT


def test_parse_deleted_id():
    payload = {"typeWebhook": "messageDeleted", "idMessage": "DEL001", "timestamp": 1700000000}
    assert parse_deleted_id(payload) == "DEL001"


def test_raw_json_stored():
    payload = _payload(
        "incomingMessageReceived",
        "MSG011",
        "textMessage",
        {"textMessageData": {"textMessage": "raw"}},
    )
    row = parse_message(payload)
    assert row["raw_json"] is payload
