"""RAG gravado em lotes: não pode perder chunk nem quebrar o schema entre lotes."""

import pandas as pd

from src.common import Config
from src.curated.build import gerar_rag


def _df(n_docs, ano_nulo_em):
    return pd.DataFrame([{
        "doc_id": f"doc{i}", "titulo": f"Título {i}", "autor": "Autora", "instituicao": "UFMG",
        "programa": "Programa", "ano": None if i == ano_nulo_em else 2000 + i % 25,
        "tipo": "Dissertação", "area_projeto": "Saúde", "idioma": "por",
        "direitos": "Acesso Aberto", "url_registro": "http://x", "split": "treino",
    } for i in range(n_docs)])


def test_rag_em_varios_lotes_com_ano_nulo_no_segundo_lote(tmp_path):
    n = 250  # lote é de 200 documentos: força dois lotes
    df = _df(n, ano_nulo_em=210)
    textos = {f"doc{i}": " ".join(f"palavra{w}" for w in range(300)) for i in range(n)}
    cfg = Config({"curated": {"rag": {"tamanho_chunk_palavras": 100, "sobreposicao_palavras": 10}}})

    res = gerar_rag(df, textos, tmp_path, cfg)
    lido = pd.read_parquet(res["arquivo"])

    assert res["documentos"] == n
    assert len(lido) == res["chunks"] == 750
    assert lido.loc[lido["doc_id"] == "doc210", "meta_ano"].isna().all()


def test_documento_descartado_na_descontaminacao_nao_vira_chunk(tmp_path):
    df = _df(3, ano_nulo_em=-1)
    df.loc[1, "split"] = "descartado_contaminado"
    textos = {f"doc{i}": " ".join(["termo"] * 120) for i in range(3)}
    cfg = Config({"curated": {"rag": {"tamanho_chunk_palavras": 100, "sobreposicao_palavras": 10}}})

    res = gerar_rag(df, textos, tmp_path, cfg)

    assert "doc1" not in set(pd.read_parquet(res["arquivo"])["doc_id"])


def test_chunk_preserva_quebra_de_linha_do_texto():
    # Juntar linhas com espaço criava telefone/CPF falso a partir de tabela
    # ("1999\n9889 6596") e o verificador do Curated parava o pipeline.
    from src.curated.build import _chunkar

    texto = "\n".join(f"linha {i} 1999\n9889 6596" for i in range(40))
    pedacos = list(_chunkar(texto, tamanho=60, sobreposicao=10))
    assert pedacos and all("\n" in p for p in pedacos)
    assert all(p in texto for p in pedacos)
    assert sum(len(p.split()) for p in pedacos[:1]) == 60
