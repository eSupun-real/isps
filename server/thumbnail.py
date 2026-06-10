"""
thumbnail.py — Generate thumbnail previews for uploaded documents
"""

import os
import base64
import io
from pathlib import Path

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(Path(__file__).parent.parent / "uploads")))


def generate_pdf_thumbnail(pdf_path: str, width: int = 200) -> str:
    """Generate a thumbnail PNG from the first page of a PDF. Returns base64 encoded PNG."""
    try:
        from pdf2image import convert_from_bytes
        from PIL import Image
        
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        
        pages = convert_from_bytes(pdf_bytes, dpi=150, first_page=1, last_page=1)
        if not pages:
            return None
            
        img = pages[0]
        aspect = img.height / img.width
        thumb_height = int(width * aspect)
        img.thumbnail((width, thumb_height), Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()
    except Exception as e:
        return None


def generate_docx_thumbnail(docx_path: str, width: int = 200) -> str:
    """Generate a thumbnail PNG preview for DOCX. Returns base64 encoded PNG."""
    try:
        import docx
        from PIL import Image, ImageDraw, ImageFont
        
        doc = docx.Document(docx_path)
        text_content = "\n".join(p.text for p in doc.paragraphs[:10] if p.text.strip())[:200]
        
        img = Image.new("RGB", (width, 120), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        y = 10
        for line in text_content.split("\n")[:6]:
            draw.text((10, y), line[:50], fill=(30, 30, 30), font=font)
            y += 16
            
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()
    except Exception as e:
        return None


def get_document_thumbnail(doc_path: str) -> dict:
    """Get thumbnail for any document type. Returns {thumbnail: base64, mime: string} or {thumbnail: None}."""
    if not doc_path or not Path(doc_path).exists():
        return {"thumbnail": None, "mime": "image/png"}
        
    path = str(doc_path).lower()
    thumb_b64 = None
    
    if path.endswith(".pdf"):
        thumb_b64 = generate_pdf_thumbnail(doc_path)
    elif path.endswith(".docx") or path.endswith(".doc"):
        thumb_b64 = generate_docx_thumbnail(doc_path)
    
    return {"thumbnail": thumb_b64, "mime": "image/png"}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result = get_document_thumbnail(sys.argv[1])
        print(result["thumbnail"] if result["thumbnail"] else "No thumbnail generated")