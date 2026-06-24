"""Multi-source paper ingestion — arXiv, DOI, bioRxiv, direct PDF, HuggingFace.

Dispatches a paper reference to the right fetcher based on the input format,
returns a unified PaperContent object.
"""

from __future__ import annotations

import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Literal

import httpx

from .ingestion import parse_pdf, extract_reference_titles
from .models import PaperContent

PaperSource = Literal["arxiv", "doi", "biorxiv", "pdf", "huggingface"]

ARXIV_ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
ARXIV_URL_PATTERN = re.compile(
    r"^https?://(www\.)?(arxiv\.org|alphaxiv\.org)/(abs|pdf)/"
)
ARXIV_PREFIX_PATTERN = re.compile(
    r"^https?://(www\.)?(arxiv\.org/abs/|alphaxiv\.org/abs/)"
)
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
DOI_URL_PATTERN = re.compile(r"^https?://(dx\.)?doi\.org/")
BIORXIV_URL_PATTERN = re.compile(
    r"^https?://(www\.)?(biorxiv|medrxiv)\.org/"
)
BIORXIV_ID_PATTERN = re.compile(r"^biorxiv[:/]", re.I)
PDF_URL_PATTERN = re.compile(r"^https?://\S+\.pdf$", re.I)
HF_PAPERS_API = "https://huggingface.co/api/papers"


@dataclass(slots=True)
class SourceDetection:
    source: PaperSource
    paper_id: str
    source_url: str


def detect_source(ref: str) -> SourceDetection:
    """Identify the paper source and extract a canonical ID from the input."""
    stripped = ref.strip()

    # arXiv ID (e.g. 2603.09229)
    if ARXIV_ID_PATTERN.match(stripped):
        return SourceDetection("arxiv", stripped, f"https://arxiv.org/abs/{stripped}")

    # arXiv / AlphaXiv URL
    if ARXIV_URL_PATTERN.match(stripped):
        paper_id = ARXIV_PREFIX_PATTERN.sub("", stripped).strip("/").split("v")[0]
        # Handle /pdf/ links
        paper_id = paper_id.replace("/pdf/", "/abs/").split("/abs/")[-1]
        return SourceDetection("arxiv", paper_id, f"https://arxiv.org/abs/{paper_id}")

    # DOI URL (https://doi.org/10.xxxx/...)
    if DOI_URL_PATTERN.match(stripped):
        doi = stripped.split("doi.org/")[-1]
        return SourceDetection("doi", doi, f"https://doi.org/{doi}")

    # Bare DOI (10.xxxx/...)
    if DOI_PATTERN.match(stripped):
        return SourceDetection("doi", stripped, f"https://doi.org/{stripped}")

    # bioRxiv / medRxiv URL
    if BIORXIV_URL_PATTERN.match(stripped):
        # Extract the DOI from the URL (biorxiv URLs contain DOIs)
        doi_match = re.search(r"(10\.\d{4,9}/\S+)", stripped)
        if doi_match:
            return SourceDetection("biorxiv", doi_match.group(1), stripped)
        return SourceDetection("biorxiv", stripped, stripped)

    # Direct PDF URL
    if PDF_URL_PATTERN.match(stripped):
        return SourceDetection("pdf", stripped, stripped)

    # HuggingFace papers (numeric IDs sometimes used)
    return SourceDetection("huggingface", stripped, stripped)


def is_arxiv_ref(ref: str) -> bool:
    return detect_source(ref).source == "arxiv"


async def fetch_from_arxiv(
    arxiv_id_or_url: str,
    github_url: str = "",
) -> PaperContent:
    """Fetch via arXiv API + PDF parsing (existing logic, migrated here)."""
    import arxiv

    arxiv_id = ARXIV_PREFIX_PATTERN.sub("", arxiv_id_or_url).strip("/").split("v")[0]

    last_error = None
    for attempt in range(5):
        try:
            client = arxiv.Client()
            search = arxiv.Search(id_list=[arxiv_id])
            result = next(client.results(search))

            with tempfile.TemporaryDirectory() as tmpdir:
                if not result.pdf_url:
                    raise ValueError(f"No PDF URL for arXiv paper: {arxiv_id}")
                pdf_path = os.path.join(tmpdir, f"{arxiv_id}.pdf")
                urllib.request.urlretrieve(result.pdf_url, pdf_path)
                full_text, sections, fig_captions, tables = parse_pdf(pdf_path)

            ref_section = sections.get("references", sections.get("bibliography", ""))

            if not github_url:
                github_match = re.search(
                    r"https?://github\.com/[a-zA-Z0-9\-_./]+", result.summary
                )
                if github_match:
                    github_url = github_match.group(0)

            return PaperContent(
                paper_id=arxiv_id,
                source="arxiv",
                title=result.title,
                authors=[author.name for author in result.authors],
                abstract=result.summary,
                full_text=full_text,
                sections=sections,
                figures_captions=fig_captions,
                tables_text=tables,
                references_titles=extract_reference_titles(ref_section),
                github_url=github_url,
                source_url=f"https://arxiv.org/abs/{arxiv_id}",
            )
        except arxiv.HTTPError as exc:
            last_error = exc
            if exc.status == 429:
                import asyncio
                await asyncio.sleep(2.0 * (2 ** attempt))
                continue
            raise
        except StopIteration:
            raise ValueError(f"Paper not found: {arxiv_id}")

    # Rate-limited — try HF fallback
    if last_error and last_error.status == 429:
        return await _fetch_from_hf_fallback(arxiv_id)

    raise last_error or ValueError(f"Failed to fetch arXiv paper: {arxiv_id}")


async def _fetch_from_hf_fallback(arxiv_id: str) -> PaperContent:
    """Fetch paper metadata from HuggingFace Papers API as fallback."""
    url = f"{HF_PAPERS_API}/{arxiv_id}"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    title = data.get("title", "")
    authors = [a.get("name", "") for a in data.get("authors", [])]
    summary = data.get("summary", "") or data.get("ai_summary", "")
    github_url = ""
    github_match = re.search(r"https?://github\.com/[a-zA-Z0-9\-_./]+", summary)
    if github_match:
        github_url = github_match.group(0)

    return PaperContent(
        paper_id=arxiv_id,
        source="huggingface",
        title=title,
        authors=authors,
        abstract=summary,
        full_text="",
        sections={"abstract": summary},
        figures_captions=[],
        tables_text=[],
        references_titles=[],
        github_url=github_url,
        source_url=f"https://huggingface.co/papers/{arxiv_id}",
    )


async def fetch_from_doi(
    doi: str,
    github_url: str = "",
) -> PaperContent:
    """Fetch paper via DOI — resolve to publisher, try to get PDF or metadata.

    Uses Crossref API for metadata and attempts to find an open-access PDF
    via the DOI redirect. Falls back to abstract-only if PDF isn't accessible.
    """
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True
    ) as client:
        # Crossref metadata
        try:
            cr_response = await client.get(f"https://api.crossref.org/works/{doi}")
            if cr_response.status_code == 200:
                cr_data = cr_response.json().get("message", {})
                title = cr_data.get("title", [""])[0]
                authors = [
                    f"{a.get('given', '')} {a.get('family', '')}".strip()
                    for a in cr_data.get("author", [])
                ]
                abstract = cr_data.get("abstract", "") or ""
                # Clean HTML tags from Crossref abstract
                abstract = re.sub(r"<[^>]+>", "", abstract).strip()
                references = cr_data.get("reference", [])
                ref_titles = [
                    r.get("article-title", r.get("unstructured", ""))
                    for r in references
                    if isinstance(r, dict)
                ][:50]
            else:
                title = doi
                authors = []
                abstract = ""
                ref_titles = []
        except httpx.HTTPError:
            title = doi
            authors = []
            abstract = ""
            ref_titles = []

        # Try to find a PDF via Unpaywall (open-access finder)
        pdf_text = ""
        sections: dict[str, str] = {}
        fig_captions: list[str] = []
        tables: list[str] = []
        if abstract:
            sections["abstract"] = abstract

        unpaywall_email = "research@paper2product.ai"
        try:
            up_url = f"https://api.unpaywall.org/v2/{doi}?email={unpaywall_email}"
            up_response = await client.get(up_url)
            if up_response.status_code == 200:
                up_data = up_response.json()
                best_oa = up_data.get("best_oa_location", {})
                pdf_url = best_oa.get("url_for_pdf") if best_oa else None
                if not pdf_url and best_oa:
                    pdf_url = best_oa.get("url")

                if pdf_url:
                    try:
                        pdf_response = await client.get(pdf_url)
                        if pdf_response.status_code == 200 and "pdf" in pdf_response.headers.get("content-type", "").lower():
                            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                                tmp.write(pdf_response.content)
                                tmp_path = tmp.name
                            pdf_text, sections, fig_captions, tables = parse_pdf(tmp_path)
                            os.unlink(tmp_path)
                    except Exception:
                        pass  # PDF extraction failed, fall back to metadata only
        except Exception:
            pass  # Unpaywall failed, metadata-only is fine

    # Search for github link in abstract
    if not github_url:
        gh_match = re.search(r"https?://github\.com/[a-zA-Z0-9\-_./]+", abstract)
        if gh_match:
            github_url = gh_match.group(0)

    return PaperContent(
        paper_id=doi,
        source="doi",
        title=title or doi,
        authors=authors,
        abstract=abstract,
        full_text=pdf_text,
        sections=sections,
        figures_captions=fig_captions,
        tables_text=tables,
        references_titles=ref_titles,
        github_url=github_url,
        source_url=f"https://doi.org/{doi}",
    )


async def fetch_from_biorxiv(
    biorxiv_url_or_doi: str,
    github_url: str = "",
) -> PaperContent:
    """Fetch paper from bioRxiv/medRxiv via their API."""
    # Extract DOI from URL or use as-is
    doi_match = re.search(r"(10\.\d{4,9}/\S+)", biorxiv_url_or_doi)
    doi = doi_match.group(1) if doi_match else biorxiv_url_or_doi

    # bioRxiv API
    server = "biorxiv" if "biorxiv" in biorxiv_url_or_doi.lower() else "medrxiv"
    api_url = f"https://api.biorxiv.org/details/{server}/10.1101/{doi.split('/')[-1]}/na/json"

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True
    ) as client:
        try:
            response = await client.get(api_url)
            data = response.json()
            collection = data.get("collection", [])
            if collection:
                paper_data = collection[0]
                title = paper_data.get("title", "")
                authors_str = paper_data.get("authors", "")
                authors = [a.strip() for a in authors_str.split(";") if a.strip()]
                abstract = paper_data.get("abstract", "")
                doi = paper_data.get("doi", doi)

                # Try to get PDF
                pdf_url = paper_data.get("jats", "")  # Not always PDF
                sections = {"abstract": abstract} if abstract else {}

                if not github_url:
                    gh_match = re.search(r"https?://github\.com/[a-zA-Z0-9\-_./]+", abstract)
                    if gh_match:
                        github_url = gh_match.group(0)

                return PaperContent(
                    paper_id=doi,
                    source="biorxiv",
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    full_text="",
                    sections=sections,
                    figures_captions=[],
                    tables_text=[],
                    references_titles=[],
                    github_url=github_url,
                    source_url=f"https://doi.org/{doi}",
                )
        except httpx.HTTPError:
            pass

    # Fallback: treat as DOI
    return await fetch_from_doi(doi, github_url)


async def fetch_from_pdf(
    pdf_url: str,
    github_url: str = "",
) -> PaperContent:
    """Fetch and parse a direct PDF URL. Extracts metadata from the PDF content."""
    async with httpx.AsyncClient(
        timeout=60.0, follow_redirects=True
    ) as client:
        response = await client.get(pdf_url)
        response.raise_for_status()

        if "pdf" not in response.headers.get("content-type", "").lower():
            raise ValueError(f"URL did not return a PDF: {pdf_url}")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

    try:
        full_text, sections, fig_captions, tables = parse_pdf(tmp_path)
    finally:
        os.unlink(tmp_path)

    # Try to extract title from first non-empty line
    title = pdf_url.split("/")[-1].replace(".pdf", "")
    for section_name, content in sections.items():
        if section_name != "preamble" and content.strip():
            first_line = content.strip().split("\n")[0]
            if len(first_line) < 200 and first_line:
                title = first_line
                break

    abstract = sections.get("abstract", "")

    if not github_url:
        gh_match = re.search(r"https?://github\.com/[a-zA-Z0-9\-_./]+", full_text[:5000])
        if gh_match:
            github_url = gh_match.group(0)

    # Use URL as paper_id
    paper_id = pdf_url.split("/")[-1].replace(".pdf", "")[:50]

    return PaperContent(
        paper_id=paper_id,
        source="pdf",
        title=title,
        authors=[],  # Can't reliably extract from arbitrary PDFs
        abstract=abstract,
        full_text=full_text,
        sections=sections,
        figures_captions=fig_captions,
        tables_text=tables,
        references_titles=extract_reference_titles(
            sections.get("references", sections.get("bibliography", ""))
        ),
        github_url=github_url,
        source_url=pdf_url,
    )


async def fetch_paper(
    ref: str,
    github_url: str = "",
) -> PaperContent:
    """Main dispatch — detect source and fetch from the right place."""
    detection = detect_source(ref)

    if detection.source == "arxiv":
        return await fetch_from_arxiv(ref, github_url)
    if detection.source == "doi":
        return await fetch_from_doi(detection.paper_id, github_url)
    if detection.source == "biorxiv":
        return await fetch_from_biorxiv(ref, github_url)
    if detection.source == "pdf":
        return await fetch_from_pdf(ref, github_url)
    # huggingface fallback
    return await _fetch_from_hf_fallback(detection.paper_id)
