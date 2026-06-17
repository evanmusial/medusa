from __future__ import annotations

from pathlib import Path

from app.config import get_settings


class OcrService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        if self.settings.enable_google_vision and self.settings.google_application_credentials:
            try:
                from google.cloud import vision

                self.client = vision.ImageAnnotatorClient()
                self.vision = vision
            except Exception:
                self.client = None

    def image_to_text(self, path: Path) -> str | None:
        if not self.client:
            return None
        content = path.read_bytes()
        image = self.vision.Image(content=content)
        response = self.client.document_text_detection(image=image)
        if response.error.message:
            raise RuntimeError(response.error.message)
        return response.full_text_annotation.text or None
