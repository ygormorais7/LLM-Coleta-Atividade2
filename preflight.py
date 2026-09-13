#!/usr/bin/env python3
"""
Verificação pré-voo.

Responde a uma pergunta só: este projeto pode fazer sua primeira requisição
a um servidor de verdade?

Três níveis:
  BLOQUEIO — não rode. Sai com código 1.
  AVISO    — rode com atenção, mas saiba o que está pendente.
  OK       — verificado.

Rode isto antes de abrir o tmux. A maior parte dos problemas de coleta é
configuração esquecida, não bug — e configuração esquecida custa caro quando
descoberta na trigésima requisição a um servidor alheio.

    python preflight.py
    python preflight.py --config config/config.yaml
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from src.common import Config, RAIZ

BLOQUEIOS: list[str] = []
AVISOS: list[str] = []
OKS: list[str] = []

PLACEHOLDERS = ("seu.email@", "PREENCHA", "exemplo.br", "contato@exemplo",
                "NÃO DECLARADA", "TROQUE", "xxx")


def bloqueio(msg: str) -> None:
    BLOQUEIOS.append(msg)


def aviso(msg: str) -> None:
    AVISOS.append(msg)


def ok(msg: str) -> None:
    OKS.append(msg)


def _e_placeholder(valor) -> bool:
    texto = str(valor or "")
    return (not texto) or any(p.lower() in texto.lower() for p in PLACEHOLDERS)


# --------------------------------------------------------------------------
def checar_identificacao(cfg: Config) -> None:
    contato = cfg.get_path("projeto.contato", "")
    if _e_placeholder(contato) or "@" not in contato:
        bloqueio(
            f"projeto.contato ainda é placeholder ({contato!r}). Esse e-mail vai "
            "no User-Agent de TODA requisição: é por ele que um administrador "
            "fala com você em vez de bloquear seu IP."
        )
    else:
        ok(f"contato: {contato}")

    if _e_placeholder(cfg.get_path("projeto.area_rotulo")):
        bloqueio("projeto.area_rotulo não preenchido.")
    else:
        ok(f"área: {cfg.get_path('projeto.area_rotulo')} "
           f"(slug: {cfg.get_path('projeto.area_slug')})")


def checar_inventario(cfg: Config) -> int:
    taxonomia = cfg.get_path("inventario.taxonomia", "")
    if _e_placeholder(taxonomia):
        bloqueio("inventario.taxonomia não declarada. Sem isso o escopo do corpus "
                 "é indefinido e o DATACARD não fecha.")
    else:
        ok(f"taxonomia declarada: {taxonomia}")

    fonte = cfg.get_path("coleta.fonte_inventario", "bdtd_api")
    ok(f"fonte de inventário: {fonte}")

    habilitadas = 0
    capes = cfg.get_path("inventario.fontes.capes", {}) or {}
    if capes.get("habilitada"):
        arquivos: list[Path] = []
        for padrao in capes.get("arquivos", []):
            arquivos.extend(sorted(RAIZ.glob(padrao)))
        if not arquivos:
            bloqueio("CAPES habilitada mas nenhum arquivo encontrado. Baixe os "
                     "CSV em dadosabertos.capes.gov.br para data/externo/capes/.")
        else:
            habilitadas += 1
            ok(f"CAPES: {len(arquivos)} arquivo(s)")
            aviso("A CAPES não linka texto completo. Sozinha, ela produz "
                  "inventário com 0% de resolução — precisa de uma fonte OAI junto.")

    for i, f in enumerate(cfg.get_path("inventario.fontes.oai", []) or [], 1):
        if not f.get("habilitada"):
            continue
        endpoint = f.get("endpoint", "")
        if _e_placeholder(endpoint) or not endpoint.startswith("http"):
            bloqueio(f"fonte OAI #{i} habilitada com endpoint inválido: {endpoint!r}. "
                     "Rode: python -m src.raw.inventario descobrir --base <url>")
            continue
        habilitadas += 1
        ok(f"OAI #{i}: {endpoint} (prefix={f.get('metadata_prefix')}, "
           f"ore={'sim' if f.get('prefix_binarios') else 'não'})")
        if not f.get("prefix_binarios"):
            aviso(f"fonte OAI #{i} sem prefix_binarios: cada documento vai custar "
                  "uma requisição extra à página HTML do repositório. Se o "
                  "`descobrir` listou `ore`, ligue.")
        if not int(f.get("limite", 0)):
            aviso(f"fonte OAI #{i} sem `limite`. No piloto, ponha um teto explícito.")

    if habilitadas == 0:
        bloqueio("Nenhuma fonte de inventário habilitada. Não há o que coletar.")
    return habilitadas


def checar_evidencia(cfg: Config) -> None:
    dir_rel = cfg.dir_relatorios()
    evidencias = list(dir_rel.glob("evidencia_*.json"))
    if not evidencias:
        bloqueio(
            "Nenhuma evidência de robots.txt em " + str(dir_rel) + ". "
            "Rode `python -m src.raw.inventario descobrir --base <url>` para cada "
            "fonte ANTES de coletar. É o anexo da seção 3 do protocolo, e é o que "
            "prova o que o servidor autorizava na data da coleta."
        )
    else:
        ok(f"evidência de robots.txt: {len(evidencias)} arquivo(s)")


def checar_evidencia_bdtd_csv(cfg: Config) -> None:
    """Cada domínio dos candidatos do inventário da BDTD precisa de evidência de robots.txt."""
    import re
    import urllib.parse

    fonte = cfg.get_path("inventario.fontes.bdtd_csv", {}) or {}
    if not fonte.get("habilitada"):
        return
    if not (RAIZ / fonte.get("arquivo", "")).exists():
        bloqueio(f"inventario.fontes.bdtd_csv habilitada, mas {fonte.get('arquivo')} não existe.")
        return
    from src.raw.inventario import candidatos_bdtd

    dominios = sorted({urllib.parse.urlsplit(c["url_landing"]).netloc for c in candidatos_bdtd(cfg)})
    evidencias = " ".join(p.name for p in cfg.dir_relatorios().glob("evidencia_robots_*.json"))
    faltando = [d for d in dominios if re.sub(r"[^a-z0-9]+", "_", d.lower()) not in evidencias]
    if faltando:
        bloqueio(f"Sem evidência de robots.txt para {len(faltando)} domínio(s) do inventário BDTD: "
                 f"{', '.join(faltando)}. Rode: python -m src.raw.inventario robots")
    else:
        ok(f"evidência de robots.txt para os {len(dominios)} domínios do inventário BDTD")


def checar_protocolo() -> None:
    caminho = RAIZ / "docs" / "PROTOCOLO_DE_COLETA.md"
    if not caminho.exists():
        bloqueio("docs/PROTOCOLO_DE_COLETA.md não existe.")
        return
    texto = caminho.read_text(encoding="utf-8")
    pendentes = texto.count("CONFIRMAR")
    if pendentes > 12:
        bloqueio(f"Protocolo com {pendentes} campos CONFIRMAR pendentes. "
                 "Preencha as seções 0 a 4 antes da primeira requisição — "
                 "protocolo escrito depois da coleta não é protocolo.")
    elif pendentes:
        aviso(f"Protocolo com {pendentes} campos CONFIRMAR pendentes. "
              "Aceitável para o piloto se as seções 0 a 4 já estiverem fechadas.")
    else:
        ok("protocolo sem pendências marcadas")


def checar_conduta(cfg: Config) -> None:
    rps = float(cfg.get_path("coleta.http.requisicoes_por_segundo", 0.5))
    rps_rep = float(cfg.get_path("coleta.http.rps_repositorios", 0.33))
    if rps > 1.0 or rps_rep > 0.5:
        bloqueio(f"Ritmo agressivo demais (fonte={rps}/s, repositório={rps_rep}/s). "
                 "O protocolo declara 1 req/2s e 1 req/3s.")
    else:
        ok(f"ritmo: {1/rps:.1f}s entre requisições na fonte, "
           f"{1/rps_rep:.1f}s por domínio de repositório")

    if not cfg.get_path("coleta.http.respeitar_robots", True):
        bloqueio("respeitar_robots está desligado.")
    else:
        ok("robots.txt respeitado")

    teto = int(cfg.get_path("coleta.max_pdfs", 0))
    if teto == 0:
        aviso("coleta.max_pdfs = 0 (sem teto). Num piloto, ponha um teto.")
    else:
        ok(f"teto de downloads: {teto}")


def checar_recursos(cfg: Config) -> None:
    n_alvo = int(cfg.get_path("inventario.amostragem.n_alvo", 300))
    teto = int(cfg.get_path("coleta.max_pdfs", 0)) or n_alvo
    # ~5 MB por PDF, mais ~1,5x para texto extraído e trabalho intermediário
    estimado_gb = teto * 5 * 2.5 / 1024
    livre_gb = shutil.disk_usage(RAIZ).free / (1024 ** 3)
    if livre_gb < estimado_gb * 1.5:
        bloqueio(f"Espaço insuficiente: {livre_gb:.1f} GB livres, estimativa de "
                 f"{estimado_gb:.1f} GB para {teto} documentos.")
    else:
        ok(f"disco: {livre_gb:.1f} GB livres, estimativa de {estimado_gb:.1f} GB")

    for modulo, motivo in [
        ("requests", "HTTP"), ("bs4", "resolução de landing page"),
        ("pandas", "camada Staging"), ("pyarrow", "Parquet"),
        ("fitz", "extração de PDF"), ("ftfy", "correção de encoding"),
        ("langdetect", "detecção de idioma"), ("datasketch", "dedup fuzzy"),
    ]:
        try:
            __import__(modulo)
        except ImportError:
            aviso(f"`{modulo}` ausente ({motivo}). Não bloqueia a camada Raw, "
                  "mas quebra mais adiante.")

    if cfg.get_path("processed.extracao.ocr_habilitado", False):
        try:
            saida = subprocess.run(["tesseract", "--list-langs"],
                                   capture_output=True, text=True, timeout=20)
            if "por" in saida.stdout:
                ok("tesseract com idioma `por`")
            else:
                aviso("tesseract sem idioma `por`: apt install tesseract-ocr-por")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            aviso("OCR habilitado mas tesseract não encontrado. "
                  "Teses de Saúde antigas são escaneadas com frequência.")

    for camada in ("raw", "staging", "processed", "curated"):
        try:
            d = cfg.dir_camada(camada)
            (d / ".escrita_ok").write_text("x")
            (d / ".escrita_ok").unlink()
        except OSError as exc:
            bloqueio(f"sem permissão de escrita em data/{camada}: {exc}")


def checar_ambiente() -> None:
    if os.environ.get("TMUX"):
        ok("rodando dentro do tmux")
    else:
        aviso("fora do tmux. Para a coleta completa, use tmux — a sessão "
              "sobrevive à queda do ssh.")


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Verificação pré-voo da coleta")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = Config.carregar(args.config)

    print("=" * 72)
    print("  VERIFICAÇÃO PRÉ-VOO")
    print(f"  config: {cfg.get('_arquivo')}")
    print("=" * 72)

    checar_identificacao(cfg)
    checar_inventario(cfg)
    checar_evidencia(cfg)
    checar_evidencia_bdtd_csv(cfg)
    checar_protocolo()
    checar_conduta(cfg)
    checar_recursos(cfg)
    checar_ambiente()

    for msg in OKS:
        print(f"  OK       {msg}")
    for msg in AVISOS:
        print(f"  AVISO    {msg}")
    for msg in BLOQUEIOS:
        print(f"  BLOQUEIO {msg}")

    print("-" * 72)
    if BLOQUEIOS:
        print(f"{len(BLOQUEIOS)} bloqueio(s), {len(AVISOS)} aviso(s). NÃO colete ainda.")
        return 1
    print(f"0 bloqueios, {len(AVISOS)} aviso(s). Liberado.")
    print("Comece em primeiro plano com limite baixo. tmux só depois que o "
          "piloto fechar limpo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
