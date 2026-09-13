"""Padronização: cada variação real vista no Staging vira um valor só."""

import pandas as pd
import pytest

from src.processed.padroniza import (padronizar_ano, padronizar_idioma, padronizar_metadados,
                                     padronizar_tipo)


@pytest.mark.parametrize("bruto, esperado", [
    ("Português", "pt"), ("por", "pt"), ("pt", "pt"), ("pt-BR", "pt"),
    ("eng", "en"), ("Inglês", "en"), ("fra", "fr"), ("spa", "es"),
    ("N/A", None), ("", None), (None, None), ("por | eng", "pt"),
])
def test_idioma(bruto, esperado):
    assert padronizar_idioma(bruto) == esperado


@pytest.mark.parametrize("bruto, esperado", [
    ("Dissertação de mestrado", "dissertação de mestrado"),
    ("Tese de doutorado", "tese de doutorado"),
    ("masterThesis", "dissertação de mestrado"),
    ("doctoralThesis", "tese de doutorado"),
    ("dissertacao", "dissertação de mestrado"),
    ("tese", "tese de doutorado"),
    ("Artigo", None), (None, None),
])
def test_tipo(bruto, esperado):
    assert padronizar_tipo(bruto) == esperado


@pytest.mark.parametrize("bruto, esperado", [
    (2019, 2019), ("2016.0", 2016), (2016.0, 2016), ("1868", 1868),
    ("0025", None), ("2999", None), (None, None), (float("nan"), None),
])
def test_ano(bruto, esperado):
    assert padronizar_ano(bruto) == esperado


def test_metadados_guardam_o_valor_bruto_ao_lado():
    df = pd.DataFrame([{"doc_id": "a", "idioma": "Português", "tipo": "Tese de doutorado", "ano": "2020"},
                       {"doc_id": "b", "idioma": "N/A", "tipo": "Artigo", "ano": None}])
    saida = padronizar_metadados(df).set_index("doc_id")
    assert (saida.loc["a", "idioma"], saida.loc["a", "idioma_bruto"]) == ("pt", "Português")
    assert (saida.loc["a", "tipo"], saida.loc["a", "ano"]) == ("tese de doutorado", 2020)
    assert pd.isna(saida.loc["b", "idioma"]) and pd.isna(saida.loc["b", "ano"])
    assert str(saida["ano"].dtype) == "Int64"


def test_coluna_ausente_e_ignorada():
    assert list(padronizar_metadados(pd.DataFrame({"doc_id": ["a"]})).columns) == ["doc_id"]
