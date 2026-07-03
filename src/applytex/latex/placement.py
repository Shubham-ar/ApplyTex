"""Sacred vs flex zone detection from LaTeX structure."""

from __future__ import annotations

import re
from typing import Any


def _experience_body(tex: str) -> str:
    """Return text inside the Experience section, if detectable."""
    patterns = [
        # Standard LaTeX \section
        r"\\section\*?\{[Ee]xperience\}(.*?)(?=\\section|\Z)",
        r"\\section\*?\{[Ww]ork [Ee]xperience\}(.*?)(?=\\section|\Z)",
        r"\\section\*?\{[Pp]rofessional [Ee]xperience\}(.*?)(?=\\section|\Z)",
        # Custom rSection environment (resume.cls and similar)
        r"\\begin\{rSection\}\{[Ee]xperience\}(.*?)\\end\{rSection\}",
        r"\\begin\{rSection\}\{[Ww]ork [Ee]xperience\}(.*?)\\end\{rSection\}",
        r"\\begin\{rSection\}\{[Pp]rofessional [Ee]xperience\}(.*?)\\end\{rSection\}",
    ]
    for pat in patterns:
        m = re.search(pat, tex, flags=re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1)
    return tex


def _split_blocks(section_text: str) -> list[str]:
    """Split experience section into role/project blocks."""
    parts = re.split(
        r"(?=\\subsection\*?\{)|(?=\\textbf\{)|(?=\\cvitem\{)|(?=\\resumeSubheading)",
        section_text,
    )
    blocks = [p.strip() for p in parts if p.strip() and len(p.strip()) > 20]
    if not blocks and section_text.strip():
        blocks = [b.strip() for b in re.split(r"\n\s*\n", section_text) if len(b.strip()) > 20]
    return blocks


def _block_label(block: str) -> str:
    """Short human label for a block (company/title line)."""
    for pat in (
        r"\\textbf\{([^{}]+)\}",
        r"\\subsection\*?\{([^{}]+)\}",
        r"\\cvitem\{([^{}]+)\}",
    ):
        m = re.search(pat, block)
        if m:
            return m.group(1).strip()[:80]
    line = block.strip().splitlines()[0] if block.strip() else "block"
    return re.sub(r"\\[a-zA-Z]+", "", line).strip()[:80] or "block"


def detect_zones(tex: str, placement_cfg: dict) -> dict[str, Any]:
    """Detect sacred and flex zones from master.tex heuristics."""
    sacred_roles = int(placement_cfg.get("sacred_roles", 1))
    exp = _experience_body(tex)
    blocks = _split_blocks(exp)

    sacred_raw = blocks[:sacred_roles]
    flex_raw = blocks[sacred_roles:]

    projects = _projects_body(tex)
    if projects.strip():
        flex_raw.append(projects)

    return {
        "sacred_blocks": [_block_label(b) for b in sacred_raw],
        "flex_blocks": [_block_label(b) for b in flex_raw],
        "sacred_text": sacred_raw,
        "flex_text": flex_raw,
    }


def _projects_body(tex: str) -> str:
    m = re.search(
        r"\\section\*?\{[Pp]rojects?\}(.*?)(?=\\section|\Z)",
        tex,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return m.group(1) if m else ""


def zone_for_term(term: dict, zones: dict) -> str:
    """Assign flex or sacred to a plan term based on action and status."""
    if term.get("status") == "gap":
        return "none"
    if term.get("status") == "exact":
        return "summary_light"
    if term.get("action") in ("swap_label", "append_adjacent"):
        return "flex"
    if term.get("status") == "adjacent":
        return "flex"
    return "summary_light"
