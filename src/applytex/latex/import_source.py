"""Copy user LaTeX resume sources into ~/.applytex/latex/."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from applytex import config

_ASSET_SUFFIXES = {".cls", ".sty", ".bib", ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}
_STANDARD_DOCUMENT_CLASSES = {
    "article", "report", "book", "letter", "slides", "beamer", "memoir", "scrartcl",
}


def _pick_main_tex(folder: Path) -> Path:
    """Choose the main .tex file inside an Overleaf-style folder."""
    preferred = folder / "main.tex"
    if preferred.exists():
        return preferred

    tex_files = sorted(folder.glob("*.tex"))
    if len(tex_files) == 1:
        return tex_files[0]

    raise FileNotFoundError(
        f"No main.tex in {folder} and multiple .tex files found: "
        + ", ".join(f.name for f in tex_files)
    )


def _copy_assets(source_dir: Path, dest_dir: Path) -> list[str]:
    """Copy class files and common assets from source_dir into dest_dir."""
    copied: list[str] = []
    for path in source_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in _ASSET_SUFFIXES:
            continue
        if path.suffix.lower() == ".pdf" and path.stem.lower() in {"resume", "cv"}:
            continue
        dest = dest_dir / path.name
        shutil.copy2(path, dest)
        copied.append(path.name)
    return copied


def documentclass_name(tex_path: Path) -> str | None:
    """Return the document class name from a .tex file, if present."""
    text = tex_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}", text)
    return match.group(1).strip() if match else None


def validate_latex_assets(master_path: Path, latex_dir: Path | None = None) -> None:
    """Ensure custom document classes have their .cls file in the latex dir."""
    latex_dir = latex_dir or master_path.parent
    cls_name = documentclass_name(master_path)
    if not cls_name or cls_name in _STANDARD_DOCUMENT_CLASSES:
        return
    cls_file = latex_dir / f"{cls_name}.cls"
    if not cls_file.exists():
        raise FileNotFoundError(
            f"master.tex uses \\documentclass{{{cls_name}}} but {cls_name}.cls was not found in "
            f"{latex_dir}. Point applytex init at the unzipped folder that contains both files."
        )


def _extract_zip_source(zip_path: Path) -> Path:
    """Extract a .zip Overleaf export to a temp folder and return the content root."""
    extract_dir = Path(tempfile.mkdtemp(prefix="applytex-latex-"))
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    children = [p for p in extract_dir.iterdir() if not p.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir


def import_latex_source(user_path: Path, main_tex: str | None = None) -> Path:
    """Copy a .tex file, folder, or .zip export into LATEX_DIR as master.tex.

    Args:
        user_path: Path to a .tex file, folder, or Overleaf .zip export.
        main_tex: When user_path is a folder, optional filename (e.g. main.tex).

    Returns:
        Path to the canonical master.tex (MASTER_TEX_PATH).
    """
    user_path = user_path.expanduser().resolve()
    if not user_path.exists():
        raise FileNotFoundError(f"Path not found: {user_path}")

    config.LATEX_DIR.mkdir(parents=True, exist_ok=True)

    if user_path.is_file() and user_path.suffix.lower() == ".zip":
        folder = _extract_zip_source(user_path)
        if main_tex:
            chosen = folder / main_tex
            if not chosen.exists():
                raise FileNotFoundError(f"TeX file not found: {chosen}")
            main_path = chosen
        else:
            main_path = _pick_main_tex(folder)
        shutil.copy2(main_path, config.MASTER_TEX_PATH)
        _copy_assets(folder, config.LATEX_DIR)
        validate_latex_assets(config.MASTER_TEX_PATH, config.LATEX_DIR)
        return config.MASTER_TEX_PATH

    if user_path.is_file():
        if user_path.suffix.lower() != ".tex":
            raise ValueError(
                f"Expected a .tex file, folder, or .zip export, got: {user_path}"
            )
        shutil.copy2(user_path, config.MASTER_TEX_PATH)
        _copy_assets(user_path.parent, config.LATEX_DIR)
        validate_latex_assets(config.MASTER_TEX_PATH, config.LATEX_DIR)
        return config.MASTER_TEX_PATH

    if user_path.is_dir():
        if main_tex:
            chosen = user_path / main_tex
            if not chosen.exists():
                raise FileNotFoundError(f"TeX file not found: {chosen}")
            main_path = chosen
        else:
            main_path = _pick_main_tex(user_path)
        shutil.copy2(main_path, config.MASTER_TEX_PATH)
        _copy_assets(user_path, config.LATEX_DIR)
        validate_latex_assets(config.MASTER_TEX_PATH, config.LATEX_DIR)
        return config.MASTER_TEX_PATH

    raise ValueError(f"Not a file or directory: {user_path}")
