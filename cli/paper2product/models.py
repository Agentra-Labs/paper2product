from dataclasses import dataclass


@dataclass
class PaperContent:
    paper_id: str
    source: str  # "arxiv", "doi", "biorxiv", "pdf", "huggingface"
    title: str
    authors: list[str]
    abstract: str
    full_text: str
    sections: dict[str, str]
    figures_captions: list[str]
    tables_text: list[str]
    references_titles: list[str]
    github_url: str = ""
    source_url: str = ""  # original URL (arxiv abs page, DOI resolver, etc.)

    @property
    def arxiv_id(self) -> str:
        """Backward-compatible accessor — returns paper_id when source is arxiv."""
        return self.paper_id if self.source == "arxiv" else ""
