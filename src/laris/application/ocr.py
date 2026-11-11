"""OCR for scanned PDFs and images (tesseract; English and Vietnamese). Inference only."""

import io
from typing import List

DEFAULT_LANG = "eng+vie"


class OcrError(RuntimeError):
    """Raised when OCR is unavailable or the input cannot be read as an image."""


def _ocr_image(data: bytes, lang: str) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise OcrError("OCR needs Pillow and pytesseract (pip install 'laris[ocr]')") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            return str(pytesseract.image_to_string(image.convert("RGB"), lang=lang))
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrError("tesseract binary not found (install tesseract-ocr)") from exc
    except Exception as exc:
        raise OcrError(f"OCR failed: {exc}") from exc


def ocr_image_bytes(data: bytes, lang: str = DEFAULT_LANG) -> str:
    return _ocr_image(data, lang).strip()


def ocr_pdf_bytes(data: bytes, lang: str = DEFAULT_LANG, max_pages: int = 50) -> str:
    """OCR the page images embedded in a scanned PDF (text-layer pages are not re-read)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise OcrError("PDF OCR needs pypdf (pip install 'laris[ocr]')") from exc
    reader = PdfReader(io.BytesIO(data))
    pages: List[str] = []
    for page in list(reader.pages)[:max_pages]:
        text = ""
        for image in page.images:
            text += "\n" + _ocr_image(image.data, lang)
        pages.append(text.strip())
    return "\n\n".join(p for p in pages if p)
