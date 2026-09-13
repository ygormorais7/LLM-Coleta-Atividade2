"""
CAMADA PROCESSED — padronização de metadados.

Cada campo vira um vocabulário fechado e o valor original fica ao lado, em
`<campo>_bruto`, para uma decisão errada aqui poder ser revista sem voltar à
Staging. Na 3ª rodada o idioma aparecia de 6 formas ("Português", "por",
"eng", "Inglês", "fra", "N/A").
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

import pandas as pd

ANO_MIN = 1800  # a BDTD tem teses médicas históricas do século XIX

_IDIOMAS = {
    "pt": {"pt", "por", "portugues", "pt-br", "pt_br", "portuguese"},
    "en": {"en", "eng", "ingles", "english"},
    "es": {"es", "spa", "espanhol", "espanol", "spanish"},
    "fr": {"fr", "fra", "fre", "frances", "french"},
    "it": {"it", "ita", "italiano", "italian"},
    "de": {"de", "ger", "deu", "alemao", "german"},
}
_CODIGO_POR_VARIANTE = {v: codigo for codigo, variantes in _IDIOMAS.items() for v in variantes}


def _chave(valor) -> str:
    texto = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    return texto.strip().lower()


def _primeiro(valor) -> str:
    """Campo com vários valores vem como "por | eng": vale o primeiro."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    return re.split(r"[|;]", str(valor))[0]


def padronizar_idioma(valor) -> str | None:
    return _CODIGO_POR_VARIANTE.get(_chave(_primeiro(valor)))


def padronizar_tipo(valor) -> str | None:
    chave = _chave(_primeiro(valor))
    if any(p in chave for p in ("disserta", "master", "mestrado")):
        return "dissertação de mestrado"
    if any(p in chave for p in ("tese", "doctor", "doutorado")):
        return "tese de doutorado"
    return None


def padronizar_ano(valor) -> int | None:
    m = re.search(r"\d{4}", _primeiro(valor))
    if not m:
        return None
    ano = int(m.group(0))
    return ano if ANO_MIN <= ano <= date.today().year else None


def padronizar_metadados(df: pd.DataFrame) -> pd.DataFrame:
    saida = df.copy()
    for campo, funcao in (("idioma", padronizar_idioma), ("tipo", padronizar_tipo),
                          ("ano", padronizar_ano)):
        if campo not in saida.columns:
            continue
        saida[f"{campo}_bruto"] = saida[campo].astype("string")
        saida[campo] = saida[campo].map(funcao)
    if "ano" in saida.columns:
        saida["ano"] = saida["ano"].astype("Int64")
    return saida
