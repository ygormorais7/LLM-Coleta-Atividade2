"""
Verificação final: nenhum produto da Curated sai com dado pessoal detectável.

Varre pré-treino, SFT, RAG, benchmark e o índice com os MESMOS detectores da
anonimização (dígito verificador e proteção de link/DOI/ORCID incluídos).
Qualquer ocorrência faz o pipeline parar com erro. Autoria bibliográfica é
ignorada por decisão de projeto (dado público de citação); URL, hash, caminho
e identificador não são texto.

    python -m src.curated.verificar_pii
"""

from __future__ import annotations

import json
import sys

import pyarrow.parquet as pq

from ..common import Config, configurar_log
from ..processed.clean import anonimizar

log = configurar_log("curated.verificar_pii")

CAMPOS_IGNORADOS = {
    "id", "doc_id", "chunk_id", "doc_gold", "id_bdtd", "duplicata_de",
    "url", "meta_url", "url_registro", "url_pdf", "arquivo",
    "sha256_arquivo", "hash_texto", "autor", "meta_autor", "fonte", "meta_fonte",
}
MAX_EXEMPLOS = 20


def _varrer(valor, campo, cfg_anon, contagem, exemplos, origem) -> None:
    if campo in CAMPOS_IGNORADOS:
        return
    if isinstance(valor, str):
        if not valor:
            return
        res = anonimizar(valor, cfg_anon)
        for achado in res.achados:
            contagem[achado["tipo"]] = contagem.get(achado["tipo"], 0) + 1
            if len(exemplos) < MAX_EXEMPLOS:
                exemplos.append({"arquivo": origem, "campo": campo, **achado})
    elif isinstance(valor, dict):
        for chave, v in valor.items():
            _varrer(v, chave, cfg_anon, contagem, exemplos, origem)
    elif isinstance(valor, list):
        for v in valor:
            _varrer(v, campo, cfg_anon, contagem, exemplos, origem)


def verificar(cfg: Config) -> dict:
    cfg_anon = cfg.get_path("processed.anonimizacao", {}) or {}
    base = cfg.dir_camada("curated")
    contagem: dict[str, int] = {}
    exemplos: list[dict] = []
    arquivos: list[str] = []

    for arq in sorted(base.glob("*/*.jsonl")):
        origem = str(arq.relative_to(base))
        arquivos.append(origem)
        with open(arq, encoding="utf-8") as fh:
            for linha in fh:
                if linha.strip():
                    _varrer(json.loads(linha), None, cfg_anon, contagem, exemplos, origem)

    # Parquet em lotes: o RAG tem ~150 mil chunks e já estourou memória uma vez.
    for arq in sorted([*base.glob("*.parquet"), *base.glob("*/*.parquet")]):
        origem = str(arq.relative_to(base))
        arquivos.append(origem)
        for lote in pq.ParquetFile(arq).iter_batches(batch_size=2000):
            for registro in lote.to_pylist():
                _varrer(registro, None, cfg_anon, contagem, exemplos, origem)

    resultado = {
        "arquivos_verificados": arquivos,
        "ocorrencias": sum(contagem.values()),
        "por_tipo": contagem,
        "exemplos_mascarados": exemplos,
    }
    destino = cfg.dir_relatorios() / "verificacao_pii_curated.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultado


def main() -> int:
    resultado = verificar(Config.carregar())
    if resultado["ocorrencias"]:
        log.error("dado pessoal encontrado no Curated: %d ocorrência(s) %s — detalhes em "
                  "data/reports/<area>/verificacao_pii_curated.json",
                  resultado["ocorrencias"], resultado["por_tipo"])
        return 1
    log.info("Curated sem dado pessoal detectável (%d arquivos verificados)",
             len(resultado["arquivos_verificados"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
