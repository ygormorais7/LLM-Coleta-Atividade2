#!/usr/bin/env python3
"""
Orquestrador do pipeline completo.

    python run_pipeline.py                       # roda as 4 camadas
    python run_pipeline.py --camadas raw         # só a coleta
    python run_pipeline.py --camadas processed curated
    python run_pipeline.py --config config/outra_area.yaml

Cada camada é independente e lê só o que a anterior gravou em disco. Isso é
o que permite reprocessar a Processed com um filtro novo sem recoletar
150 mil registros da BDTD.
"""

from __future__ import annotations

import argparse
import sys
import time

from src.common import Config, configurar_log

log = configurar_log("pipeline")

CAMADAS = ["raw", "staging", "processed", "curated"]


def _executar_camada(nome: str, cfg: Config):
    if nome == "raw":
        from src.raw.harvest import executar
    elif nome == "staging":
        from src.staging.organize import executar
    elif nome == "processed":
        from src.processed.run import executar
    elif nome == "curated":
        from src.curated.build import executar
    else:
        raise ValueError(nome)
    return executar(cfg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Pipeline BDTD -> corpus para LLMs")
    ap.add_argument("--camadas", nargs="+", choices=CAMADAS, default=CAMADAS)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = Config.carregar(args.config)
    area = cfg.get_path("projeto.area_rotulo", "?")

    print("=" * 74)
    print(f"  bdtd-corpus  |  área: {area}")
    print(f"  config: {cfg.get('_arquivo')}")
    print("=" * 74)

    t0 = time.monotonic()
    resultados = []

    for camada in args.camadas:
        print(f"\n--- camada {camada.upper()} " + "-" * (60 - len(camada)))
        inicio = time.monotonic()
        try:
            rel = _executar_camada(camada, cfg)
        except KeyboardInterrupt:
            log.warning("interrompido pelo usuário na camada %s", camada)
            return 130
        except Exception as exc:
            log.exception("camada %s falhou: %s", camada, exc)
            return 1
        duracao = time.monotonic() - inicio
        resultados.append((camada, duracao, rel))
        print(f"    concluída em {duracao:.1f}s | falhas: {len(rel.falhas)}")

    print("\n" + "=" * 74)
    print(f"{'camada':<12}{'tempo':>10}{'falhas':>10}   principais saídas")
    print("-" * 74)
    for camada, duracao, rel in resultados:
        saidas = ", ".join(
            f"{k}={v}" for k, v in list(rel.saidas.items())[:2] if isinstance(v, (int, float))
        )
        print(f"{camada:<12}{duracao:>9.1f}s{len(rel.falhas):>10}   {saidas}")
    print("-" * 74)
    print(f"total: {time.monotonic() - t0:.1f}s")
    print(f"relatórios: {cfg.dir_relatorios()}")

    # Nenhum produto sai com dado pessoal detectável: se sair, o pipeline falha.
    if "curated" in args.camadas:
        from src.curated.verificar_pii import verificar
        resultado = verificar(cfg)
        if resultado["ocorrencias"]:
            log.error("verificação de PII no Curated FALHOU: %d ocorrência(s) %s — ver "
                      "verificacao_pii_curated.json", resultado["ocorrencias"], resultado["por_tipo"])
            return 1
        print(f"verificação de PII no Curated: 0 ocorrências em "
              f"{len(resultado['arquivos_verificados'])} arquivos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
