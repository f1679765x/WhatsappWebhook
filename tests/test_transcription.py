from unittest.mock import MagicMock, patch

import app.transcription as transcription_module


@patch("app.transcription.WhisperModel")
def test_transcribe_joins_segments(mock_model_cls):
    transcription_module._model = None

    seg1, seg2 = MagicMock(), MagicMock()
    seg1.text = " Hello "
    seg2.text = " World "

    mock_model = mock_model_cls.return_value
    mock_model.transcribe.return_value = ([seg1, seg2], MagicMock())

    from app.transcription import transcribe

    result = transcribe("/path/to/audio.ogg")

    assert result == "Hello World"
    mock_model.transcribe.assert_called_once_with("/path/to/audio.ogg", beam_size=5)


@patch("app.transcription.WhisperModel")
def test_model_loaded_once(mock_model_cls):
    transcription_module._model = None

    mock_model = mock_model_cls.return_value
    mock_model.transcribe.return_value = ([], MagicMock())

    from app.transcription import transcribe

    transcribe("/a.ogg")
    transcribe("/b.ogg")

    mock_model_cls.assert_called_once()
