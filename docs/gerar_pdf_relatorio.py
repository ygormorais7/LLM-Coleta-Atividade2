"""
Gera docs/RELATORIO_ATIVIDADE_02.pdf a partir do Markdown, com LibreOffice.

    python docs/gerar_pdf_relatorio.py
"""

import subprocess
import tempfile
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent
ORIGEM = DOCS / "RELATORIO_ATIVIDADE_02.md"
ESTILO = """
body { font-family: 'Liberation Sans', Arial, sans-serif; font-size: 10.5pt; line-height: 1.35; }
h1, h2, h3 { font-family: 'Liberation Sans', Arial, sans-serif; }
h1 { font-size: 18pt; }
h2 { font-size: 14pt; margin-top: 18pt; }
h3 { font-size: 12pt; }
code, pre { font-family: 'Liberation Mono', monospace; font-size: 9pt; }
pre { background: #f3f3f3; padding: 6pt; }
blockquote { color: #333333; margin-left: 12pt; }
"""


def main() -> None:
    corpo = markdown.markdown(ORIGEM.read_text(encoding="utf-8"),
                              extensions=["tables", "fenced_code", "sane_lists"])
    # O LibreOffice ignora borda de tabela definida por CSS; o atributo HTML funciona.
    corpo = corpo.replace("<table>", '<table border="1" cellpadding="4" cellspacing="0" width="100%">')
    pagina = (f'<html><head><meta charset="utf-8"><title>Relatório — Atividade 02</title>'
              f"<style>{ESTILO}</style></head><body>{corpo}</body></html>")
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / f"{ORIGEM.stem}.html"
        html.write_text(pagina, encoding="utf-8")
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(DOCS), str(html)],
                       check=True, timeout=300)
    print(DOCS / f"{ORIGEM.stem}.pdf")


if __name__ == "__main__":
    main()
