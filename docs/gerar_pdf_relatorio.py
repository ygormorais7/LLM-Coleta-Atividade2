"""
Gera docs/RELATORIO_ATIVIDADE_02.pdf a partir do Markdown, com LibreOffice, e
confere a formatação do resultado.

    python docs/gerar_pdf_relatorio.py

Cuidados de formatação:
- corpo justificado (atributo `align` no HTML: o LibreOffice nem sempre respeita
  só o CSS); o cabeçalho (antes do primeiro título de seção) fica à esquerda;
- tabelas com borda pelo atributo HTML, largura total, fonte menor e um respiro
  depois; código longo dentro de tabela ganha pontos de quebra invisíveis;
- conversão em duas etapas (HTML → ODT → PDF): no ODT, cada linha de tabela é
  marcada para não se partir entre páginas, e cada bloco de código vira uma
  célula única, pelo mesmo motivo;
- ao fim, `conferir` procura texto que atravesse a borda de uma célula ou saia
  da margem da página, e o script sai com erro se encontrar.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent
ORIGEM = DOCS / "RELATORIO_ATIVIDADE_02.md"
DESTINO = DOCS / f"{ORIGEM.stem}.pdf"
QUEBRA = "​"  # espaço de largura zero: ponto de quebra invisível
CODIGO_LONGO = 20  # só identificador maior que isso ganha pontos de quebra
ESTILO = """
@page { size: 21cm 29.7cm; margin: 2cm; }
body { font-family: 'Liberation Sans', Arial, sans-serif; font-size: 10.5pt; line-height: 1.3; }
h1, h2, h3 { font-family: 'Liberation Sans', Arial, sans-serif; text-align: left; }
h1 { font-size: 17pt; }
h2 { font-size: 13.5pt; margin-top: 16pt; }
h3 { font-size: 11.5pt; }
th, td { font-size: 9pt; vertical-align: top; text-align: left; }
code, pre { font-family: 'Liberation Mono', monospace; font-size: 9pt; }
td code, th code { font-size: 8pt; }
pre { font-size: 8.5pt; margin-top: 0; margin-bottom: 0; }
"""
RESPIRO = '<p style="font-size:5pt; margin:0">&nbsp;</p>'


def _quebras_no_codigo_das_tabelas(html: str) -> str:
    def codigo(m: re.Match) -> str:
        if len(m.group(1)) <= CODIGO_LONGO:
            return m.group(0)
        return "<code>" + re.sub(r"([/_.=:?-])", r"\1" + QUEBRA, m.group(1)) + "</code>"

    def celula(m: re.Match) -> str:
        return re.sub(r"<code>(.*?)</code>", codigo, m.group(0), flags=re.S)

    return re.sub(r"<t[dh][^>]*>.*?</t[dh]>", celula, html, flags=re.S)


def montar_html(texto_md: str) -> str:
    corpo = markdown.markdown(texto_md, extensions=["tables", "fenced_code", "sane_lists"])
    corpo = re.sub(r"\n+(</code></pre>)", r"\1", corpo)  # sem linha em branco no fim do bloco
    corpo = _quebras_no_codigo_das_tabelas(corpo)
    # O LibreOffice ignora borda de tabela definida por CSS; o atributo HTML funciona.
    corpo = corpo.replace("<table>", '<table border="1" cellpadding="4" cellspacing="0" width="100%">')
    corpo = corpo.replace("</table>", "</table>" + RESPIRO)
    # Bloco de código como UM parágrafo monoespaçado com fundo cinza e quebras <br>:
    # um parágrafo só não se parte com as regras de viúva/órfã para blocos curtos, e
    # não sobra a faixa vazia que a célula de tabela (e o <pre>) deixavam embaixo.
    def bloco_de_codigo(m: re.Match) -> str:
        texto = "<br>".join(linha.replace(" ", "&nbsp;") for linha in m.group(1).split("\n"))
        return ("<p align=\"left\" style=\"font-family: 'Liberation Mono', monospace; font-size: 8.5pt; "
                f'background: #f3f3f3; margin-top: 4pt; margin-bottom: 8pt">{texto}</p>')

    corpo = re.sub(r"<pre><code[^>]*>(.*?)</code></pre>", bloco_de_codigo, corpo, flags=re.S)
    # Justifica só o corpo; o cabeçalho (linhas com <br>) ficaria esticado, por
    # isso vai explicitamente à esquerda (sem isso o Writer herda a justificação).
    inicio_corpo = corpo.find("<h2")
    cabecalho, resto = (corpo[:inicio_corpo], corpo[inicio_corpo:]) if inicio_corpo >= 0 else ("", corpo)
    cabecalho = cabecalho.replace("<p>", '<p align="left">')
    resto = resto.replace("<p>", '<p align="justify">')
    # O Writer não respeita `align` em <li>: o texto do item vai num <p> justificado.
    resto = re.sub(r"<li>(?!\s*<p)(.*?)</li>",
                   r'<li><p align="justify" style="margin-top:0; margin-bottom:0">\1</p></li>',
                   resto, flags=re.S)
    return (f'<html><head><meta charset="utf-8"><title>Relatório — Atividade 02</title>'
            f"<style>{ESTILO}</style></head><body>{cabecalho}{resto}</body></html>")


def _linhas_de_tabela_inteiras(odt: Path) -> None:
    """Marca toda linha de tabela do ODT com fo:keep-together (não parte entre páginas)."""
    estilo = ('<style:style style:name="LinhaInteira" style:family="table-row">'
              '<style:table-row-properties fo:keep-together="always"/></style:style>')
    temporario = odt.with_name(odt.stem + ".tmp.odt")
    with zipfile.ZipFile(odt) as origem, zipfile.ZipFile(temporario, "w", zipfile.ZIP_DEFLATED) as destino:
        for item in origem.infolist():
            dados = origem.read(item.filename)
            if item.filename == "content.xml":
                xml = dados.decode("utf-8")
                if "<office:automatic-styles/>" in xml:
                    xml = xml.replace("<office:automatic-styles/>",
                                      f"<office:automatic-styles>{estilo}</office:automatic-styles>", 1)
                else:
                    xml = xml.replace("</office:automatic-styles>", estilo + "</office:automatic-styles>", 1)
                xml = re.sub(r'(<style:style[^>]*style:family="table-row"[^>]*>\s*<style:table-row-properties)'
                             r'(?![^>]*fo:keep-together)', r'\1 fo:keep-together="always"', xml)
                xml = re.sub(r"<table:table-row(?![^>]*table:style-name)",
                             '<table:table-row table:style-name="LinhaInteira"', xml)
                dados = xml.encode("utf-8")
            compressao = zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED
            destino.writestr(item, dados, compress_type=compressao)
    shutil.move(temporario, odt)


def conferir(pdf: Path) -> list[str]:
    """Texto que atravessa uma borda vertical de tabela ou sai da margem direita."""
    import pymupdf

    avisos: list[str] = []
    with pymupdf.open(pdf) as documento:
        for numero, pagina in enumerate(documento, 1):
            verticais = []
            for desenho in pagina.get_drawings():
                for item in desenho["items"]:
                    if item[0] == "l" and abs(item[1].x - item[2].x) < 0.5:
                        verticais.append((item[1].x, min(item[1].y, item[2].y), max(item[1].y, item[2].y)))
                    elif item[0] == "re":
                        r = item[1]
                        if r.width > 1:
                            verticais += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
            limite = pagina.rect.width - 28  # margem de 2 cm ≈ 57 pt; folga de metade
            for bloco in pagina.get_text("dict")["blocks"]:
                for linha in bloco.get("lines", []):
                    for trecho in linha["spans"]:
                        if not trecho["text"].strip():
                            continue
                        x0, y0, x1, y1 = trecho["bbox"]
                        meio = (y0 + y1) / 2
                        if x1 > limite:
                            avisos.append(f"página {numero}: texto além da margem: {trecho['text'][:60]!r}")
                        elif any(x0 + 1.5 < x < x1 - 1.5 and ya < meio < yb for x, ya, yb in verticais):
                            avisos.append(f"página {numero}: texto atravessa borda de tabela: {trecho['text'][:60]!r}")
    return avisos


def converter(pagina_html: str, pasta_saida: Path, nome: str) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / f"{nome}.html"
        html.write_text(pagina_html, encoding="utf-8")
        # Filtro do Writer (não o Writer/Web): respeita margem de página e justificação.
        subprocess.run(["soffice", "--headless", "--infilter=HTML (StarWriter)", "--convert-to", "odt",
                        "--outdir", tmp, str(html)], check=True, timeout=300, capture_output=True)
        odt = Path(tmp) / f"{nome}.odt"
        _linhas_de_tabela_inteiras(odt)
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf:writer_pdf_Export",
                        "--outdir", str(pasta_saida), str(odt)], check=True, timeout=300, capture_output=True)
    return pasta_saida / f"{nome}.pdf"


def main() -> int:
    pdf = converter(montar_html(ORIGEM.read_text(encoding="utf-8")), DOCS, ORIGEM.stem)
    avisos = conferir(pdf)
    print(pdf)
    for aviso in avisos:
        print("AVISO", aviso)
    return 1 if avisos else 0


if __name__ == "__main__":
    sys.exit(main())
