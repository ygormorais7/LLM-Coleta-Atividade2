"""
CAMADA PROCESSED, etapa 3 — deduplicação.

Três níveis, porque duplicata na BDTD aparece de três jeitos diferentes:

1. EXATA — o mesmo trabalho coletado de dois repositórios (o IBICT agrega
   várias fontes; versão de mestrado depositada na universidade e num
   repositório temático viram dois registros). Resolve com SHA-256 do texto
   normalizado.

2. APROXIMADA — a mesma tese com uma folha de aprovação diferente, um
   número de página a mais, ou reextraída com OCR. Texto 98% igual, hash
   diferente. Resolve com MinHash + LSH: assinatura compacta por documento e
   busca de vizinhos com Jaccard >= limiar, sem comparar N² pares.

3. INTERNA — repetição dentro do MESMO documento (sumário que reaparece,
   cabeçalho que sobrou, tabela repetida em anexo). Regra estilo Gopher:
   remove linhas/parágrafos duplicados dentro do documento.

Por que isso não é opcional: duplicata em corpus de pré-treino é o defeito
mais caro que existe. O modelo memoriza o trecho repetido em vez de
generalizar, e — pior para a avaliação — se um documento duplicado cai
metade no treino e metade no teste, o benchmark passa a medir memorização.
O RefinedWeb removeu ~90% do Common Crawl assim, e ganhou qualidade fazendo isso.
"""

from __future__ import annotations

import re
from collections import defaultdict

from ..common import configurar_log, sha256_texto

log = configurar_log("processed.dedup")

_TOKEN = re.compile(r"\w+", re.UNICODE)


# --------------------------------------------------------------------------
# Nível 3: repetição interna
# --------------------------------------------------------------------------
def remover_repeticao_interna(texto: str, max_prop_dup: float = 0.30) -> tuple[str, dict]:
    """Remove parágrafos duplicados dentro do documento, preservando a ordem."""
    paragrafos = [p.strip() for p in texto.split("\n\n")]
    vistos: set[str] = set()
    mantidos: list[str] = []
    removidos = 0

    for p in paragrafos:
        if not p:
            continue
        chave = re.sub(r"\W+", "", p.lower())[:400]
        # Parágrafo muito curto (título, legenda) pode repetir legitimamente.
        if len(chave) < 60:
            mantidos.append(p)
            continue
        if chave in vistos:
            removidos += 1
            continue
        vistos.add(chave)
        mantidos.append(p)

    total = max(len([p for p in paragrafos if p]), 1)
    metricas = {
        "paragrafos_removidos": removidos,
        "prop_paragrafos_duplicados": round(removidos / total, 4),
    }
    metricas["excedeu_limite"] = metricas["prop_paragrafos_duplicados"] > max_prop_dup
    return "\n\n".join(mantidos), metricas


# --------------------------------------------------------------------------
# Nível 1: exata
# --------------------------------------------------------------------------
def deduplicar_exato(docs: dict[str, str]) -> tuple[set[str], dict[str, str]]:
    """
    Devolve (ids a remover, mapa id_removido -> id_mantido).

    Critério de sobrevivência: o documento mais longo do grupo; empate
    desempata pelo doc_id (determinístico entre execuções).
    """
    grupos: dict[str, list[str]] = defaultdict(list)
    for did, texto in docs.items():
        chave = re.sub(r"\s+", " ", texto).strip().lower()
        grupos[sha256_texto(chave)].append(did)

    remover, mapa = set(), {}
    for ids in grupos.values():
        if len(ids) < 2:
            continue
        representante = max(sorted(ids), key=lambda d: len(docs[d]))
        for did in ids:
            if did != representante:
                remover.add(did)
                mapa[did] = representante
    log.info("dedup exata: %d duplicatas em %d grupos", len(remover), len(grupos))
    return remover, mapa


# --------------------------------------------------------------------------
# Nível 2: aproximada
# --------------------------------------------------------------------------
def _shingles(texto: str, n: int = 5) -> set[str]:
    palavras = _TOKEN.findall(texto.lower())
    if len(palavras) < n:
        return {" ".join(palavras)} if palavras else set()
    return {" ".join(palavras[i:i + n]) for i in range(len(palavras) - n + 1)}


def deduplicar_fuzzy(
    docs: dict[str, str],
    limiar: float = 0.80,
    permutacoes: int = 128,
    shingle_n: int = 5,
) -> tuple[set[str], dict[str, str]]:
    try:
        from datasketch import MinHash, MinHashLSH
    except ImportError:
        log.warning("datasketch não instalado; dedup fuzzy ignorada")
        return set(), {}

    lsh = MinHashLSH(threshold=limiar, num_perm=permutacoes)
    assinaturas: dict[str, "MinHash"] = {}

    for did, texto in docs.items():
        conjunto = _shingles(texto, shingle_n)
        if not conjunto:
            continue
        mh = MinHash(num_perm=permutacoes)
        for s in conjunto:
            mh.update(s.encode("utf-8"))
        assinaturas[did] = mh
        lsh.insert(did, mh)

    # União-busca simples para agrupar componentes conectados.
    pai: dict[str, str] = {d: d for d in assinaturas}

    def raiz(x: str) -> str:
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    for did, mh in assinaturas.items():
        for vizinho in lsh.query(mh):
            if vizinho == did:
                continue
            a, b = raiz(did), raiz(vizinho)
            if a != b:
                pai[max(a, b)] = min(a, b)

    grupos: dict[str, list[str]] = defaultdict(list)
    for did in assinaturas:
        grupos[raiz(did)].append(did)

    remover, mapa = set(), {}
    for ids in grupos.values():
        if len(ids) < 2:
            continue
        representante = max(sorted(ids), key=lambda d: len(docs[d]))
        for did in ids:
            if did != representante:
                remover.add(did)
                mapa[did] = representante

    log.info("dedup fuzzy (jaccard>=%.2f): %d duplicatas", limiar, len(remover))
    return remover, mapa


# --------------------------------------------------------------------------
# Descontaminação treino x avaliação
# --------------------------------------------------------------------------
def descontaminar(
    treino: dict[str, str],
    avaliacao: dict[str, str],
    limiar: float = 0.80,
    permutacoes: int = 128,
    shingle_n: int = 5,
) -> set[str]:
    """
    Devolve os ids de TREINO que colidem com algum documento de avaliação.

    Sem isso, o benchmark mede memorização em vez de capacidade — e o número
    fica bonito pelo motivo errado.
    """
    try:
        from datasketch import MinHash, MinHashLSH
    except ImportError:
        log.warning("datasketch não instalado; descontaminação ignorada")
        return set()

    lsh = MinHashLSH(threshold=limiar, num_perm=permutacoes)
    for did, texto in avaliacao.items():
        mh = MinHash(num_perm=permutacoes)
        for s in _shingles(texto, shingle_n):
            mh.update(s.encode("utf-8"))
        lsh.insert(f"eval::{did}", mh)

    contaminados = set()
    for did, texto in treino.items():
        mh = MinHash(num_perm=permutacoes)
        for s in _shingles(texto, shingle_n):
            mh.update(s.encode("utf-8"))
        if lsh.query(mh):
            contaminados.add(did)

    log.info("descontaminação: %d documentos de treino colidem com avaliação", len(contaminados))
    return contaminados
