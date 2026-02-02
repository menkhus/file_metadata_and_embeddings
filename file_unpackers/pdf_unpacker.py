import io
from typing import Optional
from pathlib import Path

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

def extract_text_from_pdf(file_path: Path) -> Optional[str]:
    """Extract all text from a PDF file using PyPDF2."""
    if PyPDF2 is None:
        raise ImportError("PyPDF2 is required for PDF extraction. Please install with 'pip install PyPDF2'.")
    with open(file_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        text = []
        for page in reader.pages:
            text.append(page.extract_text() or "")
        return "\n".join(text)
