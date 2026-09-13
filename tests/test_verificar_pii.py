"""Verificação final de dados pessoais no Curated."""

import json

import pandas as pd

from src.curated.verificar_pii import verificar


def _escrever_curated(cfg, conteudo_sft):
    base = cfg.dir_camada("curated")
    (base / "sft").mkdir(parents=True, exist_ok=True)
    item = {
        "id": "d1-0",
        "messages": [{"role": "user", "content": conteudo_sft},
                     {"role": "assistant", "content": "Cuidado de enfermagem em terapia intensiva"}],
        "meta": {"doc_id": "d1", "autor": "Fulana de Tal", "titulo": "Cuidado de enfermagem",
                 "url": "https://repositorio.ufmg.br/items/1b612170-6186-452a-bbda"},
    }
    (base / "sft" / "treino.jsonl").write_text(json.dumps(item, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    (base / "rag").mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"chunk_id": "d1#00000", "doc_id": "d1", "texto": "Trecho sem dado pessoal algum.",
                   "meta_url": "https://x.br/1234-5678"}]).to_parquet(
        base / "rag" / "corpus_rag.parquet", index=False)


def test_curated_limpo_passa(cfg_tmp):
    _escrever_curated(cfg_tmp, "Proponha um título. Resumo: estudo com contato [EMAIL] já mascarado.")
    resultado = verificar(cfg_tmp)
    assert resultado["ocorrencias"] == 0
    assert resultado["arquivos_verificados"] == ["sft/treino.jsonl", "rag/corpus_rag.parquet"]


def test_email_que_escapou_e_encontrado_sem_reexpor_o_dado(cfg_tmp):
    _escrever_curated(cfg_tmp, "Contato do pesquisador: fulano@exemplo.com.br para dúvidas.")
    resultado = verificar(cfg_tmp)
    assert resultado["ocorrencias"] == 1 and resultado["por_tipo"] == {"EMAIL": 1}
    assert "fulano@" not in json.dumps(resultado)
    assert "[EMAIL]" in resultado["exemplos_mascarados"][0]["contexto"]
    assert (cfg_tmp.dir_relatorios() / "verificacao_pii_curated.json").exists()
