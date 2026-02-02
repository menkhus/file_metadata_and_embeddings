from typing import Optional
from pathlib import Path

try:
    import docx
except ImportError:
    docx = None

def extract_text_from_docx(file_path: Path) -> Optional[str]:
    """Extract all text from a Microsoft Word .docx file using python-docx."""
    if docx is None:
        raise ImportError("python-docx is required for DOCX extraction. Please install with 'pip install python-docx'.")
    doc = docx.Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])
