"""PDF parsing and reference extraction utilities.

Paper fetching has been moved to sources.py which dispatches across
arXiv, DOI, bioRxiv, direct PDF, and HuggingFace sources. This module
retains the shared PDF-parsing primitives that sources.py depends on.
"""

import re

import pdfplumber

SECTION_HEADER_PATTERN = re.compile(r"^\d+\.?\s+[A-Z]")
NAMED_SECTION_PATTERN = re.compile(
    r"^(Abstract|Introduction|Related Work|Method|Approach|"
    r"Experiments?|Results?|Discussion|Conclusion|References|"
    r"Appendix)",
    re.I,
)
FIGURE_PATTERN = re.compile(r"^(Figure|Fig\.?)\s+\d+", re.I)
TABLE_PATTERN = re.compile(r"^Table\s+\d+", re.I)
REFERENCE_TITLE_PATTERN = re.compile(r'"(.+?)"')


def parse_pdf(path: str) -> tuple[str, dict[str, str], list[str], list[str]]:
    """Parse a PDF file into (full_text, sections, figure_captions, tables)."""
    full_text_parts: list[str] = []
    current_section = "preamble"
    sections: dict[str, list[str]] = {current_section: []}
    figure_captions: list[str] = []
    tables: list[str] = []

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text_parts.append(text)

            for line in text.splitlines():
                stripped = line.strip()
                if SECTION_HEADER_PATTERN.match(stripped) and len(stripped) < 120:
                    current_section = stripped.lower()
                    sections.setdefault(current_section, [])
                elif NAMED_SECTION_PATTERN.match(stripped):
                    current_section = stripped.lower()
                    sections.setdefault(current_section, [])

                sections.setdefault(current_section, [])
                sections[current_section].append(stripped)

                if FIGURE_PATTERN.match(stripped):
                    figure_captions.append(stripped)
                if TABLE_PATTERN.match(stripped):
                    tables.append(stripped)

            for table in page.extract_tables() or []:
                tables.append(str(table))

    joined_sections = {name: "\n".join(lines) for name, lines in sections.items()}
    return "\n".join(full_text_parts), joined_sections, figure_captions, tables


def extract_reference_titles(reference_text: str) -> list[str]:
    """Extract quoted titles from a references section."""
    titles: list[str] = []
    for line in reference_text.splitlines():
        match = REFERENCE_TITLE_PATTERN.search(line)
        if match:
            titles.append(match.group(1))
    return titles[:50]
