"""Extract an uploaded decision rubric without saving files or calling models."""
from io import BytesIO

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_RUBRIC_CHARACTERS = 20000


class RubricPDFError(ValueError):
    pass


def extract_rubric_pdf(content):
    if not content or len(content) > MAX_PDF_BYTES:
        raise RubricPDFError('Choose a PDF no larger than 5 MB.')
    if not content.startswith(b'%PDF-'):
        raise RubricPDFError('This file is not a readable PDF. Choose a PDF with selectable text.')
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RubricPDFError('PDF import requires pypdf in the app Python environment.') from None
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise RubricPDFError('Choose a PDF without password protection.')
        pages = len(reader.pages)
        if not 1 <= pages <= MAX_PDF_PAGES:
            raise RubricPDFError('Choose a PDF with 1 to 20 pages.')
        parts = []
        length = 0
        for page in reader.pages:
            text = (page.extract_text() or '').strip()
            if not text:
                raise RubricPDFError('Every page must contain selectable text. Scanned pages need OCR before upload.')
            length += len(text) + (2 if parts else 0)
            if length > MAX_RUBRIC_CHARACTERS:
                raise RubricPDFError('The PDF exceeds 20,000 characters. Shorten the rubric before uploading.')
            parts.append(text)
        return {'text': '\n\n'.join(parts), 'pages': pages}
    except RubricPDFError:
        raise
    except Exception:
        raise RubricPDFError('This PDF could not be read. Choose a valid PDF with selectable text.') from None
