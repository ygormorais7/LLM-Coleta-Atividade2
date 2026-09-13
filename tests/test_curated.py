"""Curated: metadado tratado, trava de idioma no SFT e fonte honesta."""

import json

import pandas as pd

from src.common import Config
from src.curated.build import _fonte, carregar_corpus, gerar_sft

PT = ("Este estudo avaliou a qualidade do cuidado de enfermagem prestado aos pacientes internados em "
      "unidades de terapia intensiva de um hospital público, com base nos registros do prontuário e em "
      "entrevistas com a equipe, e mostrou que a adesão aos protocolos foi maior no período noturno.")
EN = ("This study evaluated the quality of nursing care provided to patients admitted to intensive care "
      "units of a public hospital, based on medical records and interviews with the staff, and showed "
      "that adherence to protocols was higher during the night shift.")


def _linha(did, resumo):
    return {"doc_id": did, "id_bdtd": f"oai:repositorio.ufmg.br:1843/{did}",
            "titulo": f"Cuidado de enfermagem em terapia intensiva {did}", "resumo": resumo,
            "palavras_chave": "enfermagem; UTI", "tipo": "Dissertação de mestrado",
            "instituicao": "Universidade Federal de Minas Gerais",
            "programa": "Programa de Pós-Graduação em Enfermagem", "autor": "Autora", "ano": 2020,
            "area_projeto": "Saúde", "idioma": "por", "direitos": "Acesso Aberto",
            "url_registro": "https://repositorio.ufmg.br/handle/1843/x", "split": "treino"}


def test_resumo_em_ingles_nao_entra_na_pergunta_do_sft(tmp_path):
    df = pd.DataFrame([_linha("pt", PT), _linha("en", EN)])
    textos = {"pt": PT * 5, "en": PT * 5}
    cfg = Config({"curated": {"finetuning": {"min_caracteres_resposta": 50, "templates_por_doc": 5}}})

    gerar_sft(df, textos, tmp_path, cfg)

    exemplos = [json.loads(l) for l in open(tmp_path / "sft" / "treino.jsonl", encoding="utf-8")]
    perguntas = [e["messages"][0]["content"] for e in exemplos]
    assert any(PT in p for p in perguntas)
    assert not any("This study" in p for p in perguntas)


def test_par_de_resumo_usa_a_introducao_sem_resumo_nem_abstract(tmp_path):
    # Achados reais: o texto tratado começa no RESUMO (resposta copiada na
    # pergunta, 186 de 243 pares) e logo depois vem o ABSTRACT (a pergunta
    # virava tradução, 109 de 178 pares).
    introducao = ("A enfermagem em terapia intensiva exige vigilância contínua e registro cuidadoso, "
                  "e a literatura aponta lacunas na adesão aos protocolos de segurança do paciente.\n") * 12
    df = pd.DataFrame([_linha("d1", PT)])
    textos = {"d1": f"RESUMO\n{PT}\nPalavras-chave: enfermagem.\nABSTRACT\n{EN}\nSUMÁRIO\n1 INTRODUÇÃO\n"
                    f"2 MÉTODOS\n1 INTRODUÇÃO\n{introducao}"}
    cfg = Config({"curated": {"finetuning": {"min_caracteres_resposta": 50, "templates_por_doc": 5}}})

    gerar_sft(df, textos, tmp_path, cfg)

    exemplos = [json.loads(l) for l in open(tmp_path / "sft" / "treino.jsonl", encoding="utf-8")]
    sintese = [e for e in exemplos if e["messages"][0]["content"].startswith("Leia a introdução")]
    assert len(sintese) == 1
    pergunta, resposta = (m["content"] for m in sintese[0]["messages"])
    assert resposta == PT
    assert PT[:80] not in pergunta and "This study" not in pergunta and "MÉTODOS" not in pergunta
    assert "A enfermagem em terapia intensiva" in pergunta


def test_trava_de_idioma_reconhece_abstract_e_palavras_chave_sem_codigo_cnpq():
    from src.curated.build import _e_portugues, _limpar_palavras_chave

    assert _e_portugues(PT) and not _e_portugues(EN)
    assert _limpar_palavras_chave("Prevalência; Temporomandibular Joint; CNPQ::CIENCIAS DA SAUDE::SAUDE COLETIVA") \
        == "Prevalência; Temporomandibular Joint"


def test_fonte_diz_de_onde_o_documento_veio():
    assert _fonte("oai:repositorio.ufmg.br:1843/42016", "https://repositorio.ufmg.br/x") \
        == "OAI-PMH repositorio.ufmg.br"
    assert _fonte("UFSC_8e53fec3", "https://repositorio.ufsc.br/handle/123/456") \
        == "inventário BDTD → repositorio.ufsc.br"


def test_curated_usa_titulo_e_resumo_tratados_da_processed(cfg_tmp):
    stg = cfg_tmp.dir_camada("staging")
    proc = cfg_tmp.dir_camada("processed")
    base = _linha("d1", "Contato: fulano@exemplo.com.br para dúvidas sobre o estudo.")
    colunas_staging = ("doc_id", "id_bdtd", "titulo", "resumo", "tipo", "instituicao", "programa",
                       "ano", "area_projeto", "idioma", "direitos", "url_registro")
    pd.DataFrame([{k: base[k] for k in colunas_staging}]).to_parquet(stg / "documentos.parquet", index=False)
    pd.DataFrame([{"doc_id": "d1", "nome": "Autora", "papel": "autor"}]).to_parquet(
        stg / "autores.parquet", index=False)
    pd.DataFrame([{"doc_id": "d1", "assunto": "enfermagem"}]).to_parquet(stg / "assuntos.parquet", index=False)
    pd.DataFrame([{"doc_id": "d1", "no_corpus": True, "palavras": 10}]).to_parquet(
        proc / "documentos.parquet", index=False)
    pd.DataFrame([{"doc_id": "d1", "titulo": base["titulo"],
                   "resumo": "Contato: [EMAIL] para dúvidas sobre o estudo."}]).to_parquet(
        proc / "metadados.parquet", index=False)
    (proc / "texto").mkdir(parents=True, exist_ok=True)
    (proc / "texto" / "d1.txt").write_text("texto do documento", encoding="utf-8")

    df, _ = carregar_corpus(cfg_tmp)

    assert df.loc[0, "resumo"] == "Contato: [EMAIL] para dúvidas sobre o estudo."
