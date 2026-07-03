"""Compile tailored .tex to PDF via tectonic or pdflatex."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from applytex.config import latex_engine

log = logging.getLogger(__name__)


def compile_tex(tex_path: Path, work_dir: Path | None = None) -> Path:
    """Compile tex_path to a sibling PDF.

    Args:
        tex_path: Path to .tex file.
        work_dir: Directory for aux outputs (defaults to tex parent).

    Returns:
        Path to generated PDF.

    Raises:
        RuntimeError: If compilation fails.
    """
    tex_path = tex_path.resolve()
    cwd = work_dir or tex_path.parent
    cwd.mkdir(parents=True, exist_ok=True)

    engine = latex_engine()
    pdf_path = tex_path.with_suffix(".pdf")

    if engine == "tectonic":
        bin_path = shutil.which("tectonic")
        if not bin_path:
            raise FileNotFoundError("tectonic not found on PATH")
        cmd = [bin_path, "--outdir", str(cwd), str(tex_path)]
    elif engine == "pdflatex":
        bin_path = shutil.which("pdflatex")
        if not bin_path:
            raise FileNotFoundError("pdflatex not found on PATH")
        cmd = [bin_path, "-interaction=nonstopmode", "-output-directory", str(cwd), str(tex_path)]
    else:
        bin_path = shutil.which(engine)
        if not bin_path:
            raise FileNotFoundError(f"{engine} not found on PATH")
        cmd = [bin_path, str(tex_path)]

    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or not pdf_path.exists():
        err = (result.stderr or result.stdout or "unknown error")[-2000:]
        raise RuntimeError(f"LaTeX compile failed ({engine}): {err}")

    return pdf_path
