"""A extração grava o histórico de páginas/OCR que a Processed reaproveita."""

import fitz

from src.common import Relatorio, ler_jsonl
from src.processed.extract import extrair_lote


def test_extracao_grava_historico_de_paginas(cfg_tmp, tmp_path, gerar_texto):
    pdf = tmp_path / "doc.pdf"
    documento = fitz.open()
    for i in range(2):
        pagina = documento.new_page()
        pagina.insert_textbox(fitz.Rect(40, 40, 560, 800), gerar_texto(i)[:2500], fontsize=9)
    documento.save(pdf)
    documento.close()

    destino = cfg_tmp.dir_camada("processed") / "texto_bruto"
    resultados = extrair_lote(cfg_tmp, [("doc_pdf", str(pdf))], destino,
                              Relatorio(camada="teste", area="teste"))

    assert resultados[0]["ok"]
    historico = list(ler_jsonl(destino.parent / "extracao_stats.jsonl"))
    assert [(h["doc_id"], h["paginas"]) for h in historico] == [("doc_pdf", 2)]
