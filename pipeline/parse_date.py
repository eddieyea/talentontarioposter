import re
import fitz


def extract_issue_date(pdf_path: str) -> str:
    """Return the letter date as YYYY-MM-DD, or empty string if not found."""
    doc = fitz.open(pdf_path)
    text = doc[0].get_text()
    doc.close()

    # Match "Date: June 24, 2026" style
    m = re.search(r"Date:\s+([A-Za-z]+ \d{1,2},\s*\d{4})", text)
    if m:
        from datetime import datetime
        try:
            dt = datetime.strptime(m.group(1).strip(), "%B %d, %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return m.group(1).strip()

    # Fallback: bare date line like "June 24, 2026"
    m2 = re.search(r"\b([A-Za-z]+ \d{1,2},\s*\d{4})\b", text)
    if m2:
        from datetime import datetime
        try:
            dt = datetime.strptime(m2.group(1).strip(), "%B %d, %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return ""
