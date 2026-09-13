"""Camada Processed de ponta a ponta, num diretório temporário."""

import pandas as pd

from src.common import escrever_jsonl
from src.processed.run import executar

RESUMO_PADRAO = "Estudo com pacientes atendidos no serviço."


def _preparar(cfg, gerar_texto, docs, orfaos=(), historico=None):
    """`docs`: tuplas (doc_id, título) ou (doc_id, título, resumo)."""
    stg = cfg.dir_camada("staging")
    proc = cfg.dir_camada("processed")
    bruto = proc / "texto_bruto"
    bruto.mkdir(parents=True, exist_ok=True)
    linhas = []
    for i, (did, titulo, *resto) in enumerate(docs):
        (bruto / f"{did}.txt").write_text(gerar_texto(i), encoding="utf-8")
        linhas.append({"doc_id": did, "titulo": titulo, "programa": "",
                       "resumo": resto[0] if resto else RESUMO_PADRAO,
                       "idioma": "Português", "tipo": "Dissertação de mestrado", "ano": 2019,
                       "tem_arquivo": True, "arquivo": f"/inexistente/{did}.pdf"})
    pd.DataFrame(linhas).to_parquet(stg / "documentos.parquet", index=False)
    pd.DataFrame({"doc_id": pd.Series(dtype=str), "assunto": pd.Series(dtype=str)}).to_parquet(
        stg / "assuntos.parquet", index=False)
    for j, did in enumerate(orfaos):
        (bruto / f"{did}.txt").write_text(gerar_texto(100 + j), encoding="utf-8")
    if historico:
        escrever_jsonl(proc / "extracao_stats.jsonl", historico)
    return proc


def _resultado(proc):
    return pd.read_parquet(proc / "documentos.parquet").set_index("doc_id")


def _metadados(proc):
    return pd.read_parquet(proc / "metadados.parquet").set_index("doc_id")


def test_texto_bruto_de_rodada_anterior_e_ignorado(cfg_tmp, gerar_texto):
    proc = _preparar(cfg_tmp, gerar_texto, [("doc_a", "Cuidado de enfermagem ao idoso")],
                     orfaos=["orfao_antigo"])
    rel = executar(cfg_tmp)
    assert rel.metricas["arquivos_brutos_orfaos_ignorados"] == 1
    assert list(_resultado(proc).index) == ["doc_a"]


def test_paginas_vem_do_historico_quando_extracao_esta_em_cache(cfg_tmp, gerar_texto):
    historico = [{"doc_id": "doc_a", "ok": True, "paginas": 42, "paginas_ocr": 3,
                  "caracteres": 10, "motor": "pymupdf+ocr", "motivo": ""}]
    proc = _preparar(cfg_tmp, gerar_texto, [("doc_a", "Cuidado de enfermagem ao idoso")],
                     historico=historico)
    rel = executar(cfg_tmp)
    linha = _resultado(proc).loc["doc_a"]
    assert rel.metricas["extraidos_nesta_execucao"] == 0
    assert (linha["paginas"], linha["paginas_ocr"], linha["motor_extracao"]) == (42, 3, "pymupdf+ocr")


def test_zootecnia_sai_por_escopo_e_catequina_fica(cfg_tmp, gerar_texto):
    proc = _preparar(cfg_tmp, gerar_texto, [
        ("doc_ok", "Cuidado de enfermagem ao idoso"),
        ("doc_bov", "Raiva bovina no norte de Minas Gerais"),
        ("doc_cat", "Efeito das catequinas do chá verde na pressão arterial"),
    ])
    executar(cfg_tmp)
    res = _resultado(proc)
    assert res.loc["doc_ok", "no_corpus"], res.loc["doc_ok", "motivos_reprovacao"]
    assert not res.loc["doc_bov", "no_corpus"]
    assert "fora_de_escopo_zootecnia" in res.loc["doc_bov", "motivos_reprovacao"]
    assert res.loc["doc_cat", "no_corpus"], res.loc["doc_cat", "motivos_reprovacao"]


def test_titulo_e_resumo_saem_anonimizados_da_processed(cfg_tmp, gerar_texto):
    proc = _preparar(cfg_tmp, gerar_texto, [
        ("doc_a", "Cuidado de enfermagem ao idoso", "Dúvidas: fulano@exemplo.com.br ou (31) 3555-0100."),
    ])
    rel = executar(cfg_tmp)
    meta = _metadados(proc)
    assert meta.loc["doc_a", "resumo"] == "Dúvidas: [EMAIL] ou [TELEFONE]."
    assert meta.loc["doc_a", "titulo"] == "Cuidado de enfermagem ao idoso"
    assert rel.metricas["pii_ocorrencias_metadados"] == 2


def test_metadados_saem_padronizados_com_valor_bruto_ao_lado(cfg_tmp, gerar_texto):
    proc = _preparar(cfg_tmp, gerar_texto, [("doc_a", "Cuidado de enfermagem ao idoso")])
    executar(cfg_tmp)
    meta = _metadados(proc)
    assert (meta.loc["doc_a", "idioma"], meta.loc["doc_a", "idioma_bruto"]) == ("pt", "Português")
    assert meta.loc["doc_a", "tipo"] == "dissertação de mestrado"
    assert meta.loc["doc_a", "ano"] == 2019


def test_sem_resumo_o_escopo_olha_o_comeco_do_texto(cfg_tmp, gerar_texto):
    proc = _preparar(cfg_tmp, gerar_texto, [
        ("doc_sem_resumo", "Avaliação de desempenho em sistemas de produção", ""),
        ("doc_ok", "Cuidado de enfermagem ao idoso", ""),
    ])
    bruto = proc / "texto_bruto" / "doc_sem_resumo.txt"
    bruto.write_text("RESUMO\n\nEste trabalho avaliou dietas para bovinos de corte em pastagem tropical.\n\n"
                     + gerar_texto(7).removeprefix("RESUMO\n\n"), encoding="utf-8")
    executar(cfg_tmp)
    res = _resultado(proc)
    assert "fora_de_escopo_zootecnia" in res.loc["doc_sem_resumo", "motivos_reprovacao"]
    assert res.loc["doc_ok", "no_corpus"], res.loc["doc_ok", "motivos_reprovacao"]


def test_relatorio_de_pii_guarda_contexto_mascarado(cfg_tmp, gerar_texto):
    proc = _preparar(cfg_tmp, gerar_texto, [
        ("doc_a", "Cuidado de enfermagem ao idoso", "Dúvidas: fulano@exemplo.com.br."),
    ])
    executar(cfg_tmp)
    relatorio = pd.read_parquet(proc / "pii_relatorio.parquet")
    linha = relatorio[relatorio["campo"] == "resumo"].iloc[0]
    assert (linha["doc_id"], linha["tipo"]) == ("doc_a", "EMAIL")
    assert "[EMAIL]" in linha["contexto"] and "fulano@" not in linha["contexto"]
