# conftest.py - shared pytest fixtures

import os

import pytest

from ccgen.engines import model_cache


@pytest.fixture(autouse=True)
def _fresh_model_caches():
    """Clear the shared model caches so a model mocked in one test never leaks into another."""
    model_cache.release_all()
    yield
    model_cache.release_all()


@pytest.fixture
def sample_segments():
    """Return a minimal list of Segment dicts for subtitle tests."""
    return [
        {
            "id": 0,
            "start": 0.0,
            "end": 3.5,
            "text": " Hello world, this is a test.",
            "words": [
                {"word": " Hello", "start": 0.0, "end": 0.5},
                {"word": " world,", "start": 0.5, "end": 1.0},
                {"word": " this", "start": 1.0, "end": 1.4},
                {"word": " is", "start": 1.4, "end": 1.6},
                {"word": " a", "start": 1.6, "end": 1.8},
                {"word": " test.", "start": 1.8, "end": 2.2},
            ],
            "language": "en",
        },
        {
            "id": 1,
            "start": 4.0,
            "end": 7.2,
            "text": " The quick brown fox jumps over the lazy dog.",
            "words": [],
            "language": "en",
        },
    ]


@pytest.fixture
def sample_translated_segments():
    """Return a minimal list of TranslatedSegment dicts for subtitle tests."""
    return [
        {
            "id": 0,
            "start": 0.0,
            "end": 3.5,
            "original": "Hello world, this is a test.",
            "translated": "Hola mundo, esto es una prueba.",
            "language": "es",
        },
        {
            "id": 1,
            "start": 4.0,
            "end": 7.2,
            "original": "The quick brown fox jumps over the lazy dog.",
            "translated": "El veloz zorro marrón salta sobre el perro perezoso.",
            "language": "es",
        },
    ]


@pytest.fixture
def tmp_wav(tmp_path):
    """Return a path to a tiny valid WAV file (44 bytes header only)."""
    wav_path = tmp_path / "test.wav"
    # Minimal PCM WAV header for a 0-sample, 16kHz mono file
    header = (
        b"RIFF\x24\x00\x00\x00WAVEfmt "
        b"\x10\x00\x00\x00\x01\x00\x01\x00"
        b"\x80\x3e\x00\x00\x00\x7d\x00\x00"
        b"\x02\x00\x10\x00"
        b"data\x00\x00\x00\x00"
    )
    wav_path.write_bytes(header)
    return str(wav_path)


@pytest.fixture(autouse=True)
def _private_workflow_store(tmp_path, monkeypatch):
    """Keep the Workflow tab's remembered and saved workflows in the test's own folder."""
    from ccgen.utils import workflow_presets

    path = str(tmp_path / "workflows.json")
    monkeypatch.setattr(workflow_presets, "store_path", lambda: path)
