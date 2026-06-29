from pathlib import Path
from types import SimpleNamespace


def test_ocr_service_falls_back_to_tesseract_after_vision_error(monkeypatch, tmp_path):
    from app.services import ocr as ocr_service
    from app.services.ocr import OcrService

    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"pretend image")

    def fail_vision(*_args, **_kwargs):
        raise RuntimeError("Vision disabled")

    service = OcrService()
    service.client = SimpleNamespace(document_text_detection=fail_vision)
    service.vision = SimpleNamespace(Image=lambda content: {"content": content})
    service.tesseract_binary = "/usr/bin/tesseract"

    def fake_run(command, **_kwargs):
        assert command[:3] == ["/usr/bin/tesseract", str(Path(image_path)), "stdout"]
        return SimpleNamespace(returncode=0, stdout="References\n1. Source text.\n", stderr="")

    monkeypatch.setattr(ocr_service.subprocess, "run", fake_run)

    assert service.image_to_text(image_path) == "References\n1. Source text.\n"
