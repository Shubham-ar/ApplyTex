"""Derive plain-text resume from LaTeX for scoring."""

from __future__ import annotations

import re
from pathlib import Path

_TEXT_COMMANDS = (
    "textbf",
    "textit",
    "emph",
    "textrm",
    "texttt",
    "underline",
    "href",
    "url",
)


def master_to_resume_txt(tex_path: Path) -> str:
    """Extract readable plain text from a LaTeX resume for LLM scoring.

    Heuristic stripper — not a full TeX parser. Good enough for scorer input.
    """
    text = tex_path.read_text(encoding="utf-8", errors="replace")

    # Extract document body only
    begin_doc = re.search(r"\\begin\{document\}", text, flags=re.IGNORECASE)
    if begin_doc:
        text = text[begin_doc.end():]
    end_doc = re.search(r"\\end\{document\}", text, flags=re.IGNORECASE)
    if end_doc:
        text = text[: end_doc.start()]

    # Remove LaTeX comments (but keep escaped \% as-is for now)
    text = re.sub(r"(?<!\\)%.*", "", text)

    # Convert escaped special chars back to literal
    text = text.replace(r"\%", "%")
    text = text.replace(r"\#", "#")
    text = text.replace(r"\{", "{")
    text = text.replace(r"\}", "}")
    text = text.replace(r"\~", "~")
    text = text.replace(r"\&", "&")
    text = text.replace(r"\$", "$")
    text = text.replace(r"\_", "_")

    # Remove \begin{...} and \end{...} environments (MUST come before generic command loop)
    text = re.sub(r"\\begin\{[a-zA-Z*]+\}", "", text)
    text = re.sub(r"\\end\{[a-zA-Z*]+\}", "\n", text)

    # Convert section/heading commands: \section{...}, \rSection{...}, etc.
    # This also handles custom commands defined in resume.cls
    for _ in range(3):
        text = re.sub(
            r"\\(?:[a-zA-Z@]+)\*?(?:\[[^\]]*\])?\{([^{}]*)\}",
            r"\n\n\1\n",
            text,
        )

    # Remove \itemsep spacing BEFORE \item conversion (to avoid \item eating \itemsep)
    text = re.sub(r"\\itemsep\s*(-?\d+\.?\d*(?:pt|em|cm|mm|in)?)\s*(\{.*?\})?\s*", "", text)
    # Convert \item to bullet points
    text = re.sub(r"\\item\s*", "\n- ", text)

    # Remove common environment artifacts
    text = text.replace("itemize", "")
    text = text.replace("enumerate", "")
    text = text.replace("description", "")

    # Handle known text-formatting commands
    for _ in range(6):
        for cmd in _TEXT_COMMANDS:
            pattern = r"\\" + cmd + r"\*?(?:\[[^\]]*\])?\{([^{}]*)\}"
            text = re.sub(pattern, r"\1", text, flags=re.IGNORECASE)

    # Strip remaining commands that take an argument
    for _ in range(6):
        text = re.sub(
            r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}",
            r"\1",
            text,
        )

    # Remove any remaining bare commands (no arguments)
    text = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?", "", text)

    # Strip bare braces
    text = text.replace("{", "").replace("}", "")

    # Convert line breaks
    text = text.replace("\\\\", "\n")

    # Remove tabular column spec artifacts: @{...}, >{...}, <{...}
    text = re.sub(r"@\{[^}]*\}", "", text)
    text = re.sub(r">\{[^}]*\}", "", text)
    text = re.sub(r"<\{[^}]*\}", "", text)
    # Remove remaining tabular column format strings like @ >l, @ l, etc.
    text = re.sub(r"@\s*>\s*[a-zA-Z@*]+", "", text)
    text = re.sub(r"@\s*[a-zA-Z@*]+", "", text)
    # Remove orphaned tabular artifacts: lone @ symbols, column separators
    text = re.sub(r"^\s*@.*", "", text, flags=re.MULTILINE)

    # Remove \itemsep spacing values that remain after the command is stripped
    text = re.sub(r"^\s*-\s*\d+\.?\d*(?:pt|em|cm|mm|in)?\s*$", "", text, flags=re.MULTILINE)

    # Normalize whitespace
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n +", "\n", text)

    return text.strip()
