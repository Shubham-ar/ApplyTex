from pathlib import Path

from applytex.latex.import_source import import_latex_source, validate_latex_assets

RESUME_TEX = r"""
\documentclass{resume}
\begin{document}
Hello
\end{document}
"""
from applytex.latex.text_export import master_to_resume_txt


SAMPLE_TEX = r"""
\documentclass{article}
\begin{document}
\section{Experience}
\textbf{Senior Engineer} at Acme Corp
\begin{itemize}
\item Built APIs with Python and FastAPI
\item Reduced latency by 40\%
\end{itemize}
\end{document}
"""


def test_master_to_resume_txt_extracts_content(tmp_path: Path) -> None:
    tex = tmp_path / "resume.tex"
    tex.write_text(SAMPLE_TEX, encoding="utf-8")
    plain = master_to_resume_txt(tex)
    assert "Senior Engineer" in plain
    assert "Acme Corp" in plain
    assert "Python" in plain
    assert "40" in plain
    assert "\\textbf" not in plain


def test_import_latex_source_single_file(tmp_path: Path, monkeypatch) -> None:
    import applytex.config as cfg

    latex_dir = tmp_path / "latex"
    master = latex_dir / "master.tex"
    monkeypatch.setattr(cfg, "LATEX_DIR", latex_dir)
    monkeypatch.setattr(cfg, "MASTER_TEX_PATH", master)

    src = tmp_path / "myresume.tex"
    src.write_text(SAMPLE_TEX, encoding="utf-8")
    cls = tmp_path / "resume.cls"
    cls.write_text("% class", encoding="utf-8")

    out = import_latex_source(src)
    assert out == master
    assert master.read_text(encoding="utf-8") == SAMPLE_TEX
    assert (latex_dir / "resume.cls").exists()


def test_validate_latex_assets_requires_custom_cls(tmp_path: Path, monkeypatch) -> None:
    import applytex.config as cfg

    latex_dir = tmp_path / "latex"
    latex_dir.mkdir()
    master = latex_dir / "master.tex"
    monkeypatch.setattr(cfg, "LATEX_DIR", latex_dir)
    monkeypatch.setattr(cfg, "MASTER_TEX_PATH", master)
    master.write_text(RESUME_TEX, encoding="utf-8")

    try:
        validate_latex_assets(master, latex_dir)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError as exc:
        assert "resume.cls" in str(exc)


def test_import_latex_source_zip(tmp_path: Path, monkeypatch) -> None:
    import zipfile

    import applytex.config as cfg

    latex_dir = tmp_path / "latex"
    master = latex_dir / "master.tex"
    monkeypatch.setattr(cfg, "LATEX_DIR", latex_dir)
    monkeypatch.setattr(cfg, "MASTER_TEX_PATH", master)

    src_dir = tmp_path / "export"
    src_dir.mkdir()
    (src_dir / "resume.tex").write_text(RESUME_TEX, encoding="utf-8")
    (src_dir / "resume.cls").write_text("% class", encoding="utf-8")
    zip_path = tmp_path / "resume.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(src_dir / "resume.tex", "resume.tex")
        zf.write(src_dir / "resume.cls", "resume.cls")

    out = import_latex_source(zip_path)
    assert out == master
    assert (latex_dir / "resume.cls").exists()
