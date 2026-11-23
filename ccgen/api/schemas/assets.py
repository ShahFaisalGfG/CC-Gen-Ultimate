# assets.py - response contract for the Manage Models catalog

from typing import Optional

from pydantic import BaseModel


class AssetOut(BaseModel):
    """One row in the Manage Models catalog, returned to the QML client."""

    id: str
    category: str
    # The group the row is shown in, e.g. "Whisper" or "Light voices (Piper)".
    engine: str
    label: str
    # The asset in a sentence, e.g. "Whisper small" in "Downloading Whisper small".
    name: str
    downloaded: bool
    size_bytes: Optional[int] = None
    approx_size_mb: Optional[int] = None
