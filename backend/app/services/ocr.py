from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.services.google_credentials import load_service_account_credentials
from app.services.preferences import get_active_google_service_account_path


class OcrService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        if self.settings.enable_google_vision:
            try:
                from google.cloud import vision

                credentials_path = get_active_google_service_account_path()
                credentials = load_service_account_credentials(credentials_path) if credentials_path else None
                self.client = vision.ImageAnnotatorClient(credentials=credentials)
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
