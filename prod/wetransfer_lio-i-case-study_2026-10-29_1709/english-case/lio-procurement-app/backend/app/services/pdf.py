import base64
import io

import pypdfium2 as pdfium
from pypdf import PdfReader

# Rendering budget for vision extraction. 150 DPI keeps footer-size print legible;
# vendor quotes rarely put anything relevant past the first few pages.
RENDER_DPI = 150
MAX_RENDERED_PAGES = 4
JPEG_QUALITY = 85


def is_pdf(content: bytes) -> bool:
    """True if the bytes carry a PDF header (don't trust the client's MIME type)."""
    return b"%PDF-" in content[:1024]


def extract_text(pdf_bytes: bytes) -> str:
    """Extract the plain text from a vendor-offer PDF (reading order, no layout)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def extract_layout_text(pdf_bytes: bytes) -> str:
    """Extract text with the page layout preserved, so table columns stay aligned.

    Plain extraction flattens tables: an item number lands right before the
    description and reads like a quantity. Layout mode keeps "Item", "Qty" and
    "Total" in their columns. Falls back to plain extraction per page.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except Exception:  # noqa: BLE001 — layout mode is best-effort
            text = page.extract_text() or ""
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        pages.append(f"--- Page {number} ---\n" + "\n".join(lines))
    return "\n\n".join(pages)


def render_pages_as_data_urls(pdf_bytes: bytes) -> list[str]:
    """Render the first pages to JPEG data URLs for a vision model.

    Covers what the text layer can't: content that only exists as an image
    (letterheads, scanned footers) and visual structure (logos, columns).
    """
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        urls = []
        for index in range(min(len(document), MAX_RENDERED_PAGES)):
            page = document[index]
            image = page.render(scale=RENDER_DPI / 72).to_pil().convert("RGB")
            page.close()
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
            urls.append(
                "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
            )
        return urls
    finally:
        document.close()
