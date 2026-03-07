from unittest.mock import MagicMock, patch

import app.media as media_module
from app.media import build_filename, delete_file, download_and_save


def test_build_filename_audio():
    name = build_filename("6594760227@c.us", "audioMessage", "voice.ogg", 1735689600)
    assert name.startswith("2025_01_01")
    assert "6594760227@c.us" in name
    assert "audio" in name
    assert name.endswith("voice.ogg")


def test_build_filename_image():
    name = build_filename("group@g.us", "imageMessage", "photo.jpg", 1735689600)
    assert "image" in name
    assert name.endswith("photo.jpg")


def test_build_filename_strips_path_traversal():
    name = build_filename("chat@c.us", "documentMessage", "../../evil.pdf", 1735689600)
    assert ".." not in name
    assert name.endswith("evil.pdf")


@patch("app.media.httpx.Client")
def test_download_and_save(mock_client_cls, tmp_path, monkeypatch):
    monkeypatch.setattr(media_module, "DATA_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.content = b"fake audio data"
    mock_client = mock_client_cls.return_value.__enter__.return_value
    mock_client.get.return_value = mock_resp

    rel = download_and_save("https://example.com/audio.ogg", "test.ogg")

    assert rel == "test.ogg"
    assert (tmp_path / "test.ogg").read_bytes() == b"fake audio data"


def test_delete_file_removes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(media_module, "DATA_DIR", tmp_path)
    f = tmp_path / "test.mp3"
    f.write_bytes(b"data")

    delete_file("test.mp3")

    assert not f.exists()


def test_delete_file_missing_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(media_module, "DATA_DIR", tmp_path)
    delete_file("nonexistent.mp3")
