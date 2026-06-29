from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.config import get_settings
from app.services.google_credentials import load_service_account_credentials
from app.services.preferences import get_active_google_service_account_path


TESSERACT_TIMEOUT_SECONDS = 45


class OcrService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        self.tesseract_binary = shutil.which("tesseract")
        if self.settings.enable_google_vision:
            try:
                from google.cloud import vision

                credentials_path = get_active_google_service_account_path()
                if not credentials_path:
                    return
                credentials = load_service_account_credentials(credentials_path)
                self.client = vision.ImageAnnotatorClient(credentials=credentials)
                self.vision = vision
            except Exception:
                self.client = None

    @property
    def available(self) -> bool:
        return bool(self.client or self.tesseract_binary)

    def _image_to_text_with_tesseract(self, path: Path) -> str | None:
        if not self.tesseract_binary:
            return None
        result = subprocess.run(
            [self.tesseract_binary, str(path), "stdout", "-l", "eng", "--psm", "6"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=TESSERACT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout or None

    def image_to_text(self, path: Path) -> str | None:
        vision_error: Exception | None = None
        if self.client:
            try:
                content = path.read_bytes()
                image = self.vision.Image(content=content)
                response = self.client.document_text_detection(image=image)
                if response.error.message:
                    raise RuntimeError(response.error.message)
                text = response.full_text_annotation.text or None
                if text:
                    return text
            except Exception as exc:
                vision_error = exc
        tesseract_text = self._image_to_text_with_tesseract(path)
        if tesseract_text:
            return tesseract_text
        if vision_error:
            raise vision_error
        return None
