"""
Cliente da API de busca da BDTD (VuFind).

A BDTD roda VuFind, que expõe uma API REST em /api/v1:
    GET /vufind/api/v1/search?lookfor=...&type=...&filter[]=...&field[]=...&page=&limit=
    GET /vufind/api/v1/record?id=...&field[]=...
    GET /vufind/api?swagger            (especificação completa dos campos)

Três coisas que valem mais que a documentação:

1) A BDTD é AGREGADORA DE METADADOS. O IBICT coleta título, autor, resumo,
   assunto etc. via OAI-PMH dos repositórios das universidades, mas o PDF
   continua hospedado na instituição de defesa. Ou seja: a API te dá o
   metadado + a URL do registro no repositório de origem; o texto completo
   exige um segundo salto (ver src/raw/fulltext.py).

2) Solr tem janela de paginação profunda (~10 mil resultados). Para áreas
   com 100 mil+ registros, paginar direto não funciona: a partir de certo
   ponto a API devolve erro ou repete resultados. A solução aqui é fatiar a
   consulta por ano de defesa (publishDate), garantindo que cada fatia caiba
   na janela. Se uma fatia anual ainda estourar, ela é subdividida por
   instituição.

3) O portal fica atrás de proteção anti-bot. Se as respostas vierem em HTML
   com "Aguarde um momento enquanto validamos sua conexão", a sessão precisa
   de cookie de navegador — daí o fallback opcional por Selenium descrito no
   README. Rate limit baixo reduz muito a chance de cair nisso.

Uso como CLI (útil para descobrir o filtro da sua área):
    python -m src.raw.bdtd_client facets --field format
    python -m src.raw.bdtd_client facets --field dc.subject.cnpq.fl_str_mv --limit 50
    python -m src.raw.bdtd_client busca  --lookfor "aprendizado de maquina" --limit 3
"""

from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterator

import requests

from ..common import Config, RateLimiter, configurar_log

log = configurar_log("raw.bdtd_client")

# Campos que pedimos à API. Pedir só o necessário deixa a resposta menor
# e a coleta mais rápida. "rawData" traz o registro Solr completo — é o que
# preserva a fidelidade exigida pela camada Raw.
CAMPOS_PADRAO = [
    "id",
    "title",
    "authors",
    "formats",
    "languages",
    "publicationDates",
    "subjects",
    "summary",
    "urls",
    "institutions",
    "rawData",
]

STATUS_RETENTAVEIS = {408, 425, 429, 500, 502, 503, 504}


class RespostaInesperada(RuntimeError):
    """A API respondeu algo que não é o JSON esperado (ex.: página anti-bot)."""


class BDTDClient:
    def __init__(self, cfg: Config, sessao: requests.Session | None = None):
        self.cfg = cfg
        self.base = cfg.get_path("coleta.base_url", "https://bdtd.ibict.br/vufind").rstrip("/")
        self.timeout = cfg.get_path("coleta.http.timeout_s", 60)
        self.tentativas = cfg.get_path("coleta.http.tentativas", 4)
        self.backoff = cfg.get_path("coleta.http.backoff_base_s", 2.0)
        self.limiter = RateLimiter(cfg.get_path("coleta.http.requisicoes_por_segundo", 0.5))
        self.sessao = sessao or requests.Session()
        self.sessao.headers.update(
            {
                "User-Agent": cfg.user_agent(),
                "Accept": "application/json",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
        )

    # ---------------------------------------------------------------- HTTP
    def _get(self, caminho: str, params: list[tuple[str, str]]) -> dict:
        url = f"{self.base}{caminho}"
        ultimo_erro: Exception | None = None

        for tentativa in range(1, self.tentativas + 1):
            self.limiter.aguardar("bdtd")
            try:
                resp = self.sessao.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                ultimo_erro = exc
                espera = self.backoff * (2 ** (tentativa - 1))
                log.warning("erro de rede (%s). retry em %.1fs", exc, espera)
                time.sleep(espera)
                continue

            if resp.status_code in STATUS_RETENTAVEIS:
                # 429 pode trazer Retry-After: respeitar é o mínimo de educação.
                espera = float(resp.headers.get("Retry-After", 0) or 0)
                espera = espera or self.backoff * (2 ** (tentativa - 1))
                log.warning("HTTP %s. retry em %.1fs", resp.status_code, espera)
                time.sleep(espera)
                continue

            resp.raise_for_status()

            try:
                return resp.json()
            except ValueError as exc:
                trecho = resp.text[:200].replace("\n", " ")
                if "validamos sua conex" in resp.text or "<html" in resp.text[:200].lower():
                    raise RespostaInesperada(
                        "A BDTD devolveu HTML (provável proteção anti-bot). "
                        "Reduza requisicoes_por_segundo ou habilite fallback_selenium. "
                        f"Trecho: {trecho}"
                    ) from exc
                raise RespostaInesperada(f"resposta não-JSON: {trecho}") from exc

        raise RespostaInesperada(f"falhou após {self.tentativas} tentativas: {ultimo_erro}")

    # -------------------------------------------------------------- Busca
    def buscar(
        self,
        lookfor: str = "",
        tipo: str = "AllFields",
        filtros: list[str] | None = None,
        campos: list[str] | None = None,
        facetas: list[str] | None = None,
        pagina: int = 1,
        limite: int = 100,
        ordenacao: str = "publishDateSort asc",
    ) -> dict:
        """Uma página de resultados. `limite` máximo aceito pelo VuFind é 100."""
        params: list[tuple[str, str]] = [
            ("lookfor", lookfor or ""),
            ("type", tipo),
            ("page", str(pagina)),
            ("limit", str(min(limite, 100))),
            ("sort", ordenacao),
        ]
        for f in filtros or []:
            params.append(("filter[]", f))
        for c in campos or CAMPOS_PADRAO:
            params.append(("field[]", c))
        for f in facetas or []:
            params.append(("facet[]", f))
        return self._get("/api/v1/search", params)

    def facetas(self, campo: str, limite: int = 50, filtros: list[str] | None = None) -> list[dict]:
        """
        Lista os valores possíveis de um campo e quantos registros cada um tem.

        É assim que você descobre o filtro exato da sua área sem chutar nome
        de campo Solr.
        """
        dados = self.buscar(
            filtros=filtros,
            campos=["id"],
            facetas=[campo],
            limite=0,
            pagina=1,
        )
        bloco = (dados.get("facets") or {}).get(campo, [])
        saida = []
        for item in bloco[:limite]:
            saida.append(
                {
                    "valor": item.get("value"),
                    "rotulo": item.get("translated", item.get("value")),
                    "total": item.get("count"),
                }
            )
        return saida

    def total_resultados(self, lookfor: str, tipo: str, filtros: list[str]) -> int:
        dados = self.buscar(lookfor=lookfor, tipo=tipo, filtros=filtros, campos=["id"], limite=0)
        return int(dados.get("resultCount", 0))

    def registro(self, ids: list[str], campos: list[str] | None = None) -> dict:
        params = [("id[]", i) for i in ids]
        for c in campos or CAMPOS_PADRAO:
            params.append(("field[]", c))
        return self._get("/api/v1/record", params)

    # --------------------------------------------------- Iteração completa
    def iterar(
        self,
        lookfor: str = "",
        tipo: str = "AllFields",
        filtros: list[str] | None = None,
        campos: list[str] | None = None,
        limite_total: int = 0,
        janela_solr: int = 9000,
    ) -> Iterator[dict]:
        """
        Percorre TODOS os registros da consulta, contornando a janela do Solr.

        Estratégia: se o total couber na janela, pagina direto. Se não couber,
        fatia por ano de defesa; se algum ano ainda não couber, fatia aquele
        ano por instituição. É o mesmo raciocínio de "particionar a chave"
        que se usa em qualquer coleta grande.
        """
        filtros = list(filtros or [])
        total = self.total_resultados(lookfor, tipo, filtros)
        log.info("consulta com %s registros no total", f"{total:,}".replace(",", "."))

        if total == 0:
            return

        if total <= janela_solr or not self.cfg.get_path("coleta.particionar_por_ano", True):
            yield from self._paginar(lookfor, tipo, filtros, campos, limite_total)
            return

        emitidos = 0
        ano_ini = int(self.cfg.get_path("coleta.ano_inicio", 1990))
        ano_fim = int(self.cfg.get_path("coleta.ano_fim", 2026))

        for ano in range(ano_ini, ano_fim + 1):
            f_ano = filtros + [f'publishDate:"{ano}"']
            total_ano = self.total_resultados(lookfor, tipo, f_ano)
            if total_ano == 0:
                continue
            log.info("ano %s: %s registros", ano, f"{total_ano:,}".replace(",", "."))

            fatias = [f_ano]
            if total_ano > janela_solr:
                # Subdivide por instituição para caber na janela.
                instituicoes = self.facetas("institution", limite=400, filtros=f_ano)
                fatias = [f_ano + [f'institution:"{i["valor"]}"'] for i in instituicoes]
                log.info("  ano %s subdividido em %d instituições", ano, len(fatias))

            for fatia in fatias:
                for reg in self._paginar(lookfor, tipo, fatia, campos, 0):
                    yield reg
                    emitidos += 1
                    if limite_total and emitidos >= limite_total:
                        return

    def _paginar(
        self,
        lookfor: str,
        tipo: str,
        filtros: list[str],
        campos: list[str] | None,
        limite_total: int,
    ) -> Iterator[dict]:
        pagina, emitidos = 1, 0
        while True:
            dados = self.buscar(
                lookfor=lookfor, tipo=tipo, filtros=filtros, campos=campos,
                pagina=pagina, limite=100,
            )
            registros = dados.get("records") or []
            if not registros:
                return
            for reg in registros:
                # Guarda de qual fatia veio: rastreabilidade dentro da Raw.
                reg["_consulta"] = {"filtros": filtros, "lookfor": lookfor, "pagina": pagina}
                yield reg
                emitidos += 1
                if limite_total and emitidos >= limite_total:
                    return
            if len(registros) < 100:
                return
            pagina += 1


# ------------------------------------------------------------------- CLI
def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Explorador da API da BDTD")
    ap.add_argument("comando", choices=["facets", "busca", "total"])
    ap.add_argument("--field", default="format")
    ap.add_argument("--lookfor", default="")
    ap.add_argument("--filtro", action="append", default=[])
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = Config.carregar(args.config)
    cli = BDTDClient(cfg)
    filtros = args.filtro or cfg.get_path("coleta.filtros", [])

    if args.comando == "facets":
        for f in cli.facetas(args.field, limite=args.limit, filtros=filtros):
            print(f"{f['total']:>10,}".replace(",", ".") + f"  {f['valor']}")
    elif args.comando == "total":
        print(cli.total_resultados(args.lookfor, "AllFields", filtros))
    else:
        dados = cli.buscar(lookfor=args.lookfor, filtros=filtros, limite=args.limit)
        print(json.dumps(dados, ensure_ascii=False, indent=2)[:8000])


if __name__ == "__main__":
    _cli()
