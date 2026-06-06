"""
ocr_extract.py — Local OCR and text extraction pipeline
Priority: 1) pdfminer (native text) → 2) pytesseract OCR (scanned/image PDFs) → 3) python-docx
"""

import sys
import base64
import json
import io
import os
import tempfile

# ── PDF native text extraction ────────────────────────────────────────────────
def extract_pdf_native(pdf_bytes: bytes) -> str:
    """Extract text from a digital PDF using pdfminer (no LLM, no OCR)."""
    try:
        from pdfminer.high_level import extract_text
        with io.BytesIO(pdf_bytes) as f:
            text = extract_text(f)
        return text.strip()
    except Exception as e:
        return ""

# ── OCR via Tesseract (for scanned/image PDFs) ────────────────────────────────
def extract_pdf_ocr(pdf_bytes: bytes) -> str:
    """Rasterise each page and run Tesseract OCR."""
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        from PIL import Image

        pages = convert_from_bytes(pdf_bytes, dpi=200)
        texts = []
        for page in pages:
            t = pytesseract.image_to_string(page, lang='eng')
            texts.append(t)
        return "\n".join(texts).strip()
    except Exception as e:
        return ""

# ── DOCX extraction ───────────────────────────────────────────────────────────
def extract_docx(docx_bytes: bytes) -> str:
    try:
        import docx
        with io.BytesIO(docx_bytes) as f:
            doc = docx.Document(f)
        paras = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paras).strip()
    except Exception as e:
        return ""

# ── EML extraction (plain text from email files) ──────────────────────────────
def extract_eml(eml_bytes: bytes) -> str:
    try:
        import email
        msg = email.message_from_bytes(eml_bytes)
        parts = []
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == 'text/plain':
                    payload = part.get_payload(decode=True)
                    if payload:
                        parts.append(payload.decode('utf-8', errors='replace'))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                parts.append(payload.decode('utf-8', errors='replace'))
        return "\n".join(parts).strip()
    except Exception:
        return ""

# ── Main dispatcher ───────────────────────────────────────────────────────────
def extract_text(b64_data: str, filename: str) -> dict:
    """
    Returns {"text": str, "method": str, "pages": int, "char_count": int}
    method: "native_pdf" | "ocr_pdf" | "docx" | "eml" | "unknown"
    """
    raw = base64.b64decode(b64_data)
    fname = filename.lower()
    text = ""
    method = "unknown"
    pages = 0

    if fname.endswith(".pdf"):
        # Try native first
        text = extract_pdf_native(raw)
        if len(text) > 100:
            method = "native_pdf"
        else:
            # Fall back to OCR
            text = extract_pdf_ocr(raw)
            method = "ocr_pdf"
            # Estimate pages
            try:
                from pdf2image import convert_from_bytes
                pages = len(convert_from_bytes(raw, dpi=72))
            except:
                pages = 0

    elif fname.endswith(".docx") or fname.endswith(".doc"):
        text = extract_docx(raw)
        method = "docx"

    elif fname.endswith(".eml"):
        text = extract_eml(raw)
        method = "eml"

    return {
        "text": text,
        "method": method,
        "pages": pages,
        "char_count": len(text)
    }

# ── CLI entrypoint (called from Node.js via child_process) ────────────────────
if __name__ == "__main__":
    inp = json.loads(sys.stdin.read())
    result = extract_text(inp["b64"], inp["filename"])
    print(json.dumps(result))
