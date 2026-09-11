"""
CAMADA PROCESSED, etapa 1 — extração de conteúdo.

Tese é o pior caso de PDF que existe: 200 páginas, sumário automático,
tabelas, fórmulas, páginas escaneadas de assinatura no meio, e uma boa
fração do acervo mais antigo é PDF-imagem sem camada de texto nenhuma.

Estratégia em três níveis:
  1. PyMuPDF página a página (rápido, cobre a maioria);
  2. se a página tem pouquíssimo caractere -> provavelmente é imagem;
  3. se a maioria das páginas é imagem -> OCR (Tesseract, pt), com teto de
     páginas para não gastar 40 minutos numa tese digitalizada inteira.

Docling entra como motor alternativo quando a estrutura importa mais que a
velocidade (mantém títulos, tabelas e ordem de leitura em Markdown).

Paralelismo: ProcessPool. Extração de PDF é CPU-bound e roda em C sob o
GIL parcialmente liberado, mas OCR e parsing pesado se beneficiam de
processos de verdade. O custo é memória: cada worker carrega sua própria
instância, então `workers` deve ficar abaixo do número de núcleos.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from ..common import Config, Relatorio, configurar_log

log = configurar_log("processed.extract")


@dataclass
class ResultadoExtracao:
    doc_id: str
    ok: bool
    texto: str = ""
    paginas: int = 0
    paginas_ocr: int = 0
    caracteres: int = 0
    motor: str = ""
    motivo: str = ""


def _extrair_pymupdf(caminho: Path, cfg_extracao: dict) -> tuple[list[str], int, list[int]]:
    """Devolve (texto por página, total de páginas, índices que precisam de OCR)."""
    import fitz  # PyMuPDF

    min_chars = int(cfg_extracao.get("min_chars_por_pagina", 60))
    paginas, precisam_ocr = [], []

    with fitz.open(caminho) as doc:
        total = doc.page_count
        for i, pagina in enumerate(doc):
            texto = pagina.get_text("text") or ""
            paginas.append(texto)
            if len(texto.strip()) < min_chars:
                precisam_ocr.append(i)
    return paginas, total, precisam_ocr


def _ocr_paginas(caminho: Path, indices: list[int], cfg_extracao: dict) -> dict[int, str]:
    """OCR só nas páginas que precisam. PyMuPDF rasteriza, Tesseract lê."""
    import fitz
    import pytesseract
    from PIL import Image
    import io

    dpi = int(cfg_extracao.get("ocr_dpi", 200))
    idioma = cfg_extracao.get("ocr_idioma", "por")
    teto = int(cfg_extracao.get("ocr_max_paginas", 60))
    indices = indices[:teto]

    saida: dict[int, str] = {}
    zoom = dpi / 72.0
    matriz = fitz.Matrix(zoom, zoom)
    with fitz.open(caminho) as doc:
        for i in indices:
            try:
                pix = doc[i].get_pixmap(matrix=matriz)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                saida[i] = pytesseract.image_to_string(img, lang=idioma)
            except Exception as exc:  # página quebrada não derruba o documento
                saida[i] = ""
                log.debug("OCR falhou na página %d de %s: %s", i, caminho.name, exc)
    return saida


def _extrair_docling(caminho: Path) -> tuple[list[str], int, list[int]]:
    from docling.document_converter import DocumentConverter

    conversor = DocumentConverter()
    resultado = conversor.convert(str(caminho))
    markdown = resultado.document.export_to_markdown()
    return [markdown], 0, []


def extrair_um(tarefa: tuple[str, str, dict]) -> dict:
    """Executada dentro do worker. Argumentos e retorno precisam ser picklable."""
    doc_id_, caminho_str, cfg_extracao = tarefa
    caminho = Path(caminho_str)
    motor = cfg_extracao.get("motor", "pymupdf")

    if not caminho.exists():
        return asdict(ResultadoExtracao(doc_id_, False, motivo="arquivo_ausente"))

    try:
        if motor == "docling":
            paginas, total, precisam = _extrair_docling(caminho)
        else:
            paginas, total, precisam = _extrair_pymupdf(caminho, cfg_extracao)
    except Exception as exc:
        return asdict(ResultadoExtracao(doc_id_, False, motor=motor, motivo=f"parser:{exc}"))

    ocr_usado = 0
    proporcao_vazia = len(precisam) / max(len(paginas), 1)
    if cfg_extracao.get("ocr_habilitado", True) and proporcao_vazia > 0.5 and precisam:
        try:
            textos_ocr = _ocr_paginas(caminho, precisam, cfg_extracao)
            for i, texto in textos_ocr.items():
                if texto.strip():
                    paginas[i] = texto
                    ocr_usado += 1
        except Exception as exc:
            log.debug("OCR indisponível para %s: %s", caminho.name, exc)

    # Marcador de página: preservado até a limpeza, porque é o que permite
    # detectar cabeçalho/rodapé repetido depois.
    texto = "\n\n<<<PAGINA>>>\n\n".join(paginas).strip()

    if len(texto) < 200:
        return asdict(
            ResultadoExtracao(doc_id_, False, paginas=total, motor=motor, motivo="texto_insuficiente")
        )

    return asdict(
        ResultadoExtracao(
            doc_id=doc_id_,
            ok=True,
            texto=texto,
            paginas=total,
            paginas_ocr=ocr_usado,
            caracteres=len(texto),
            motor=motor + ("+ocr" if ocr_usado else ""),
        )
    )


def extrair_lote(cfg: Config, tarefas: list[tuple[str, str]], destino: Path, rel: Relatorio) -> list[dict]:
    """Roda a extração em paralelo e grava um .txt por documento."""
    cfg_ex = dict(cfg.get_path("processed.extracao", {}) or {})
    workers = int(cfg_ex.get("workers", max(1, (os.cpu_count() or 2) // 2)))
    destino.mkdir(parents=True, exist_ok=True)

    entradas = [(d, c, cfg_ex) for d, c in tarefas]
    resultados: list[dict] = []

    log.info("extraindo %d arquivos com %d workers (motor=%s)", len(entradas), workers, cfg_ex.get("motor"))

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(extrair_um, t): t[0] for t in entradas}
        for i, fut in enumerate(as_completed(futuros), 1):
            did = futuros[fut]
            try:
                res = fut.result()
            except Exception as exc:
                rel.falha(did, "excecao_worker", str(exc))
                continue

            if res["ok"]:
                (destino / f"{did}.txt").write_text(res.pop("texto"), encoding="utf-8")
            else:
                rel.falha(did, res.get("motivo", "extracao_falhou"))
                res.pop("texto", None)
            resultados.append(res)

            if i % 50 == 0:
                log.info("%d/%d extraídos", i, len(entradas))

    ok = sum(1 for r in resultados if r["ok"])
    log.info("extração: %d ok / %d (%.1f%%)", ok, len(resultados), 100 * ok / max(len(resultados), 1))
    return resultados
