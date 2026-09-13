"""
ESTÁGIO 1 — fontes de inventário.

Trocamos a origem da lista sem mexer nos estágios 2 e 3. Duas fontes, um
schema comum:

  CAPES  — dados abertos (CSV/XLSX, origem Sucupira). Cobre 1987 em diante,
           traz área de avaliação e área de conhecimento. NÃO traz link para
           o texto completo.

  OAI-PMH — qualquer provedor: OpenAIRE, LA Referencia, ou um DSpace direto.
           Traz identificador e landing page. Raramente traz o bitstream em
           oai_dc; para isso é preciso metadataPrefix=ore.

Aviso de moldura, que é a diferença mais importante entre as duas:

  A CAPES lista tudo que foi DECLARADO à Sucupira, tenha ou não texto digital
  em algum lugar. O OAI de agregador lista o que foi DEPOSITADO e COLHIDO.
  O segundo é subconjunto próprio do primeiro. Isso significa que a taxa de
  resolução contra uma moldura CAPES é pior E não é uniforme entre estratos:
  IES grandes com repositório maduro resolvem bem, IES pequenas e anos
  antigos resolvem mal.

  Consequência: amostragem estratificada sobre moldura CAPES sem controle de
  não-resposta produz corpus enviesado. Ver `inventario.amostrar`, que sorteia
  com reposição dentro do estrato e mede a taxa de resolução por estrato.
"""

from __future__ import annotations

import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

from ..common import Config, RateLimiter, configurar_log

log = configurar_log("raw.fontes")

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ore": "http://www.openarchives.org/ore/terms/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dim": "http://www.dspace.org/xmlns/dspace/dim",
    "etdms": "http://www.ndltd.org/standards/metadata/etdms/1.0/",
}


@dataclass
class RegistroInventario:
    """Schema comum a todas as fontes. É o contrato do Estágio 1."""

    fonte: str                       # "capes" | "oai:<host>"
    chave_origem: str                # id na fonte de origem
    titulo: str = ""
    autor: str = ""
    ano: int | None = None
    ies: str = ""
    programa: str = ""
    area: str = ""
    taxonomia: str = ""              # QUAL classificação define `area`
    tipo: str = ""                   # tese | dissertação
    idioma: str = ""
    identificador: str = ""          # handle ou DOI, quando houver
    endpoint: str = ""               # de onde veio, para enriquecer depois
    url_landing: str = ""
    url_binario: str = ""            # só quando a fonte entrega (ore/REST)
    resumo: str = ""
    palavras_chave: str = ""
    extra: dict = field(default_factory=dict)

    def para_dict(self) -> dict:
        return asdict(self)


# ==========================================================================
# CAPES
# ==========================================================================
# Os nomes das colunas mudam entre os recortes (1987-2012, 2013-2016,
# 2017-2020, 2021-2024). Em vez de fixar um mapa por ano, casamos por regex
# sobre o nome normalizado. Se a CAPES publicar mais um recorte com nomes
# novos, o leitor continua funcionando.
_PADROES_CAPES = {
    "titulo": [r"^nm_producao$", r"titulo", r"^ds_titulo"],
    "autor": [r"^nm_discente$", r"^nm_autor$", r"autor"],
    "ano": [r"^an_base$", r"^nr_ano", r"ano.*(base|defesa)", r"^dt_.*defesa"],
    "ies": [r"^nm_entidade_ensino$", r"^nm_ies$", r"entidade.*ensino", r"^sg_entidade"],
    "programa": [r"^nm_programa", r"programa"],
    "area_avaliacao": [r"^nm_area_avaliacao$", r"area.*avaliacao"],
    "area_conhecimento": [r"^nm_area_conhecimento$", r"area.*conhecimento"],
    "grande_area": [r"^nm_grande_area", r"grande.*area"],
    "tipo": [r"^nm_grau_academico$", r"^ds_grau", r"grau.*academico", r"^nm_producao_tipo"],
    "resumo": [r"^ds_resumo$", r"resumo"],
    "palavras_chave": [r"^ds_palavra_chave$", r"palavra.*chave"],
    "paginas": [r"^nr_paginas$", r"paginas"],
    "uf": [r"^sg_uf", r"^nm_uf"],
    "regiao": [r"^nm_regiao", r"^nm_grande_regiao"],
}


def _normalizar_nome_coluna(nome: str) -> str:
    nome = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", nome.lower()).strip("_")


def bate_algum_termo(texto: str, termos: list[str], palavra_inteira: bool = False) -> bool:
    """
    `termos` já normalizados. Inclusão usa trecho (aceita radical como
    "obstetric"); exclusão usa palavra inteira, porque trecho solto faz
    "equina" casar dentro de "catequina" e excluir tese de nutrição.
    """
    alvo = _normalizar_nome_coluna(texto)
    if palavra_inteira:
        alvo = f"_{alvo}_"
        return any(f"_{t}_" in alvo for t in termos if t)
    return any(t in alvo for t in termos if t)


def bate_exclusao(texto: str, termos: list[str], permitidas: list[str] | None = None) -> bool:
    """
    Exclusão de escopo por palavra inteira, depois de apagar do texto as
    expressões permitidas (`escopo.expressoes_permitidas` no config).

    Achados reais, lendo os 42 excluídos como zootecnia em 2026-09-13: "pé
    equino" (ortopedia infantil), "dentina radicular bovina" (odontologia in
    vitro), "soro fetal bovino" e "albumina sérica bovina" (reagentes de
    laboratório) tiravam tese de Saúde do corpus.
    """
    alvo = f"_{_normalizar_nome_coluna(texto)}_"
    for expressao in permitidas or []:
        expressao = _normalizar_nome_coluna(expressao)
        if expressao:
            alvo = re.sub(rf"(?<=_){re.escape(expressao)}(?=_)", "", alvo)
    return any(f"_{t}_" in alvo for t in termos if t)


def _mapear_colunas(colunas) -> dict[str, str]:
    normalizadas = {_normalizar_nome_coluna(c): c for c in colunas}
    mapa: dict[str, str] = {}
    for campo, padroes in _PADROES_CAPES.items():
        for padrao in padroes:
            achado = next((orig for norm, orig in normalizadas.items()
                           if re.search(padrao, norm)), None)
            if achado:
                mapa[campo] = achado
                break
    return mapa


def _ler_tabela(caminho: Path) -> pd.DataFrame:
    """CAPES publica CSV com ; e encoding que varia entre latin-1 e utf-8."""
    if caminho.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(caminho, dtype=str)
    for encoding in ("utf-8", "latin-1", "cp1252"):
        for sep in (";", ",", "\t"):
            try:
                df = pd.read_csv(
                    caminho, sep=sep, dtype=str, encoding=encoding,
                    on_bad_lines="skip", low_memory=False,
                )
                if df.shape[1] > 3:
                    log.debug("%s lido com encoding=%s sep=%r", caminho.name, encoding, sep)
                    return df
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
    raise IOError(f"não consegui ler {caminho}: encoding/separador desconhecidos")


def ler_capes(
    arquivos: list[Path],
    campo_area: str = "area_avaliacao",
    valores_area: list[str] | None = None,
) -> list[RegistroInventario]:
    """
    Lê os CSV/XLSX da CAPES e filtra pela área escolhida.

    `campo_area` decide a TAXONOMIA do seu corpus: "area_avaliacao" (o cluster
    de avaliação da CAPES, ex. Medicina I-III, Saúde Coletiva, Enfermagem),
    "area_conhecimento" (a tabela CNPq) ou "grande_area". Essas três NÃO são
    equivalentes e não reproduzem a faceta da BDTD. Qualquer que seja a
    escolha, ela precisa aparecer no DATACARD junto com a tabela de
    correspondência entre as três.
    """
    valores_norm = {_normalizar_nome_coluna(v) for v in (valores_area or [])}
    registros: list[RegistroInventario] = []

    for caminho in arquivos:
        df = _ler_tabela(Path(caminho))
        mapa = _mapear_colunas(df.columns)
        faltando = [c for c in ("titulo", "autor", "ies") if c not in mapa]
        if faltando:
            log.warning("%s: colunas não identificadas %s — arquivo ignorado",
                        Path(caminho).name, faltando)
            continue

        col_area = mapa.get(campo_area) or mapa.get("area_conhecimento") or mapa.get("area_avaliacao")
        if col_area is None:
            log.warning("%s: sem coluna de área — arquivo ignorado", Path(caminho).name)
            continue

        if valores_norm:
            mascara = df[col_area].fillna("").map(
                lambda v: _normalizar_nome_coluna(v) in valores_norm
            )
            df = df[mascara]

        log.info("%s: %d registros após filtro de área", Path(caminho).name, len(df))

        for linha in df.itertuples(index=False):
            def pega(campo: str) -> str:
                col = mapa.get(campo)
                if not col:
                    return ""
                valor = getattr(linha, col.replace(" ", "_"), None)
                if valor is None:
                    valor = dict(zip(df.columns, linha)).get(col)
                return "" if pd.isna(valor) else str(valor).strip()

            titulo = pega("titulo")
            if not titulo:
                continue
            ano_bruto = pega("ano")
            m = re.search(r"(19|20)\d{2}", ano_bruto)

            registros.append(
                RegistroInventario(
                    fonte="capes",
                    chave_origem=f"capes:{Path(caminho).stem}:{len(registros)}",
                    titulo=titulo,
                    autor=pega("autor"),
                    ano=int(m.group(0)) if m else None,
                    ies=pega("ies"),
                    programa=pega("programa"),
                    area=pega(campo_area) or pega("area_conhecimento"),
                    taxonomia=f"capes.{campo_area}",
                    tipo=pega("tipo"),
                    idioma="por",
                    resumo=pega("resumo"),
                    palavras_chave=pega("palavras_chave"),
                    extra={
                        "uf": pega("uf"),
                        "regiao": pega("regiao"),
                        "paginas": pega("paginas"),
                        "area_avaliacao": pega("area_avaliacao"),
                        "area_conhecimento": pega("area_conhecimento"),
                        "grande_area": pega("grande_area"),
                        # a CAPES não linka o texto completo: a resolução vai
                        # depender inteiramente do casamento com uma fonte OAI
                        "tem_link_fulltext": False,
                    },
                )
            )

    log.info("CAPES: %d registros no inventário", len(registros))
    return registros


# ==========================================================================
# Inventário da BDTD exportado pelo grupo
# ==========================================================================
def _texto_ou_vazio(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return str(valor)


def ler_inventario_bdtd(caminho: Path, cfg_fonte: dict,
                        excluir_extra: list[str] | None = None,
                        permitidas: list[str] | None = None) -> list[RegistroInventario]:
    """
    Lê o inventário da BDTD (CSV ou Parquet com id, titulo, autor, ano, tipo,
    instituicao, repositorio, url, direitos, idioma, assuntos) e aplica os
    filtros deste projeto: acesso aberto com URL, instituições excluídas,
    escopo em título + assuntos (inclusão por radical, exclusão por palavra
    inteira) e, no piloto, lista de instituições e limite por instituição.
    """
    caminho = Path(caminho)
    df = pd.read_parquet(caminho) if caminho.suffix == ".parquet" else pd.read_csv(caminho, low_memory=False)
    df = df[df["url"].notna()]
    if cfg_fonte.get("somente_acesso_aberto", True):
        df = df[df["direitos"].fillna("").str.lower() == "openaccess"]
    excluidas = {str(i).upper() for i in cfg_fonte.get("excluir_instituicoes", []) or []}
    if excluidas:
        df = df[~df["instituicao"].fillna("").str.upper().isin(excluidas)]
    escolhidas = {str(i).upper() for i in cfg_fonte.get("instituicoes", []) or []}
    if escolhidas:
        df = df[df["instituicao"].fillna("").str.upper().isin(escolhidas)]

    incluir = [_normalizar_nome_coluna(t) for t in cfg_fonte.get("filtro_assunto", []) or []]
    excluir = [_normalizar_nome_coluna(t)
               for t in [*(cfg_fonte.get("excluir_assunto") or []), *(excluir_extra or [])]]
    contexto = df["titulo"].fillna("").astype(str) + " " + df["assuntos"].fillna("").astype(str)
    if incluir:
        mascara = contexto.map(lambda t: bate_algum_termo(t, incluir))
        df, contexto = df[mascara], contexto[mascara]
    if excluir:
        df = df[~contexto.map(lambda t: bate_exclusao(t, excluir, permitidas))]

    limite = int(cfg_fonte.get("limite_por_instituicao", 0) or 0)
    if limite:
        df = (df.sample(frac=1.0, random_state=int(cfg_fonte.get("semente", 42)))
              .groupby("instituicao", group_keys=False).head(limite))

    registros = []
    for linha in df.to_dict("records"):
        ano = pd.to_numeric(linha.get("ano"), errors="coerce")
        assuntos = _texto_ou_vazio(linha.get("assuntos"))
        registros.append(RegistroInventario(
            fonte="bdtd_inventario",
            chave_origem=_texto_ou_vazio(linha.get("id")),
            titulo=_texto_ou_vazio(linha.get("titulo")),
            autor=_texto_ou_vazio(linha.get("autor")),
            ano=None if pd.isna(ano) else int(ano),
            ies=_texto_ou_vazio(linha.get("instituicao")),
            area=assuntos,
            taxonomia="busca 'saúde' na BDTD + filtro de escopo do projeto",
            tipo=_texto_ou_vazio(linha.get("tipo")),
            idioma=_texto_ou_vazio(linha.get("idioma")),
            identificador=_texto_ou_vazio(linha.get("url")),
            url_landing=_texto_ou_vazio(linha.get("url")),
            palavras_chave=assuntos,
            extra={"direitos": _texto_ou_vazio(linha.get("direitos")),
                   "repositorio": _texto_ou_vazio(linha.get("repositorio"))},
        ))
    log.info("inventário BDTD: %d candidatos depois dos filtros", len(registros))
    return registros


# ==========================================================================
# OAI-PMH
# ==========================================================================
class ClienteOAI:
    """
    Colhedor OAI-PMH genérico. Funciona contra OpenAIRE, LA Referencia, ou o
    DSpace de uma universidade — é o mesmo protocolo.

    Detalhes do protocolo que quase toda implementação caseira erra:

      - `resumptionToken` é EXCLUSIVO: ao retomar, envie apenas
        verb + resumptionToken. Mandar metadataPrefix junto é erro
        `badArgument` e derruba a colheita no meio.
      - `503 + Retry-After` é o mecanismo NORMAL de controle de fluxo do
        OAI-PMH, não um erro. Respeitar é obrigatório, não educação.
      - Registros deletados vêm com `status="deleted"` no header e sem
        metadados. Ignore em vez de estourar.
      - `noRecordsMatch` é resposta válida para uma janela vazia.
    """

    # Falhas seguidas, sem nenhum registro novo, que interrompem a colheita.
    FALHAS_SEGUIDAS_MAX = 5

    def __init__(self, endpoint: str, cfg: Config):
        self.endpoint = endpoint.rstrip("?")
        self.cfg = cfg
        self.timeout = cfg.get_path("coleta.http.timeout_s", 60)
        self.limiter = RateLimiter(cfg.get_path("coleta.http.rps_repositorios", 0.33))
        self.sessao = requests.Session()
        self.sessao.headers.update({"User-Agent": cfg.user_agent()})
        self._aplicar_crawl_delay()

    def _aplicar_crawl_delay(self) -> None:
        """
        Honra `Crawl-delay` também na colheita OAI.

        A primeira versão desta correção cobria só o download de arquivos, e
        deixou o cliente OAI batendo a 3s num repositório que pedia 15 —
        cinco vezes mais rápido do que o administrador autorizou. Colheita de
        metadados é tráfego como qualquer outro e obedece à mesma regra.
        """
        import urllib.parse
        import urllib.robotparser
        partes = urllib.parse.urlsplit(self.endpoint)
        if not partes.netloc:
            return
        try:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{partes.scheme}://{partes.netloc}/robots.txt")
            rp.read()
            atraso = rp.crawl_delay(self.cfg.user_agent()) or rp.crawl_delay("*")
        except Exception:
            atraso = None
        if atraso:
            self.limiter.definir_intervalo(self.endpoint, float(atraso))
            log.info("%s pede Crawl-delay de %ss — adotado na colheita OAI",
                     partes.netloc, atraso)

    def _pedir(self, params: dict, tentativas: int = 5,
               erros_tolerados: tuple = ("noRecordsMatch",)) -> ET.Element:
        for tentativa in range(1, tentativas + 1):
            self.limiter.aguardar(self.endpoint)
            resp = self.sessao.get(self.endpoint, params=params, timeout=self.timeout)

            if resp.status_code == 503:
                espera = float(resp.headers.get("Retry-After", 0) or 0) or 20.0
                log.info("OAI pediu espera de %.0fs (controle de fluxo)", espera)
                time.sleep(min(espera, 300))
                continue

            resp.raise_for_status()
            raiz = ET.fromstring(resp.content)

            erro = raiz.find("oai:error", NS)
            if erro is not None:
                codigo = erro.get("code", "")
                if codigo in erros_tolerados:
                    return raiz
                raise RuntimeError(f"OAI erro {codigo}: {erro.text}")
            return raiz
        raise RuntimeError(f"OAI não respondeu após {tentativas} tentativas")

    def identify(self) -> dict:
        raiz = self._pedir({"verb": "Identify"})
        no = raiz.find("oai:Identify", NS)
        if no is None:
            return {}
        return {
            re.sub(r"\{.*\}", "", f.tag): (f.text or "").strip()
            for f in no
        }

    def list_sets(self) -> list[tuple[str, str]]:
        saida, token = [], None
        while True:
            params = {"verb": "ListSets"} if token is None else {"verb": "ListSets", "resumptionToken": token}
            raiz = self._pedir(params)
            no = raiz.find("oai:ListSets", NS)
            if no is None:
                return saida
            for s in no.findall("oai:set", NS):
                spec = (s.findtext("oai:setSpec", "", NS) or "").strip()
                nome = (s.findtext("oai:setName", "", NS) or "").strip()
                saida.append((spec, nome))
            token = (no.findtext("oai:resumptionToken", "", NS) or "").strip()
            if not token:
                return saida

    def list_metadata_formats(self, identificador: str | None = None) -> list[dict]:
        """
        Quais formatos o provedor oferece. É o que decide se você vai precisar
        raspar HTML ou não: se `ore` estiver na lista, o OAI entrega os
        bitstreams direto e o Estágio 2 vira uma leitura de XML.
        """
        params = {"verb": "ListMetadataFormats"}
        if identificador:
            params["identifier"] = identificador
        raiz = self._pedir(params)
        no = raiz.find("oai:ListMetadataFormats", NS)
        if no is None:
            return []
        return [
            {
                "prefix": (f.findtext("oai:metadataPrefix", "", NS) or "").strip(),
                "schema": (f.findtext("oai:schema", "", NS) or "").strip(),
            }
            for f in no.findall("oai:metadataFormat", NS)
        ]

    def get_record(self, identificador: str, metadata_prefix: str = "oai_dc") -> ET.Element | None:
        """Um registro específico. É a forma correta de buscar metadado
        complementar de um conjunto pequeno de documentos já selecionados."""
        raiz = self._pedir(
            {"verb": "GetRecord", "identifier": identificador,
             "metadataPrefix": metadata_prefix},
            erros_tolerados=("idDoesNotExist", "cannotDisseminateFormat", "noRecordsMatch"),
        )
        return raiz.find("oai:GetRecord/oai:record", NS)

    def _listar_intervalo(self, metadata_prefix, conjunto, desde, ate) -> Iterator[ET.Element]:
        """Um intervalo de datestamp, paginado por resumptionToken, sem fatiar."""
        yield from self.list_records(metadata_prefix, conjunto, desde, ate, limite=0)

    def _colher_janela(self, metadata_prefix, conjunto, inicio, fim, vistos: set,
                       minimo_dias: int) -> Iterator[ET.Element]:
        """
        Colhe [inicio, fim]. Se o servidor falhar no meio da paginação, divide a
        janela ao meio e tenta cada metade, até `minimo_dias`. O que falhar mesmo
        assim vai para `janelas_perdidas` — perda declarada, não silenciosa. Antes,
        2026-02-25..2026-06-25 dava HTTP 500 na UFMG e era pulada inteira.
        """
        from datetime import timedelta
        perdidas = self.__dict__.setdefault("janelas_perdidas", [])
        if self.__dict__.get("_colheita_interrompida"):
            perdidas.append({"de": inicio.date().isoformat(), "ate": fim.date().isoformat(),
                             "erro": "não tentada: colheita interrompida por falhas seguidas"})
            return
        emitiu = False
        try:
            for registro in self._listar_intervalo(metadata_prefix, conjunto,
                                                   inicio.strftime("%Y-%m-%d"),
                                                   fim.strftime("%Y-%m-%d")):
                ident = (registro.findtext("oai:header/oai:identifier", "", NS) or "").strip()
                if ident and ident in vistos:
                    continue  # janela reaberta devolve de novo o que já tinha saído
                vistos.add(ident)
                emitiu = True
                yield registro
            self._falhas_seguidas = 0
        except Exception as exc:
            # Critério de parada do protocolo (erro persistente no mesmo domínio):
            # em 2026-09-13 a UFMG devolveu HTTP 500 até para janela de 1 dia, e
            # dividir ao meio sem limite viraria centenas de requisições falhando.
            self._falhas_seguidas = 1 if emitiu else self.__dict__.get("_falhas_seguidas", 0) + 1
            if self._falhas_seguidas >= self.FALHAS_SEGUIDAS_MAX:
                self._colheita_interrompida = True
                log.error("%d falhas seguidas sem registro novo: colheita interrompida; "
                          "janela %s..%s declarada perdida (%s)",
                          self._falhas_seguidas, inicio.date(), fim.date(), exc)
                perdidas.append({"de": inicio.date().isoformat(), "ate": fim.date().isoformat(),
                                 "erro": f"interrompida após {self._falhas_seguidas} falhas seguidas: "
                                         f"{str(exc)[:250]}"})
                return
            dias = (fim - inicio).days
            if dias > minimo_dias:
                meio = inicio + timedelta(days=dias // 2)
                log.warning("janela %s..%s falhou (%s); dividindo ao meio",
                            inicio.date(), fim.date(), exc)
                yield from self._colher_janela(metadata_prefix, conjunto, inicio, meio,
                                               vistos, minimo_dias)
                yield from self._colher_janela(metadata_prefix, conjunto, meio, fim,
                                               vistos, minimo_dias)
            else:
                log.error("janela %s..%s perdida (%s)", inicio.date(), fim.date(), exc)
                perdidas.append({"de": inicio.date().isoformat(), "ate": fim.date().isoformat(),
                                 "erro": str(exc)[:300]})

    def list_records(
        self,
        metadata_prefix: str = "oai_dc",
        conjunto: str | None = None,
        desde: str | None = None,
        ate: str | None = None,
        limite: int = 0,
        janela_dias: int = 0,
        janela_minima_dias: int = 1,
    ) -> Iterator[ET.Element]:
        """
        Percorre os registros. Com `janela_dias`, fatia a consulta por
        intervalos de datestamp.

        O DSpace devolve HTTP 500 em `resumptionToken` profundo — na UFMG a
        parede fica por volta de 7.900 registros. Fatiar mantém cada consulta
        curta o bastante para nunca chegar lá. O datestamp é a data de
        indexação, não de defesa, então isto é técnica de paginação, não
        recorte temporal do corpus.
        """
        if janela_dias > 0:
            from datetime import datetime, timedelta, timezone
            inicio = datetime.fromisoformat((desde or "2000-01-01")[:10])
            fim = (datetime.fromisoformat(ate[:10]) if ate
                   else datetime.now(timezone.utc).replace(tzinfo=None))
            vistos: set[str] = set()
            emitidos = 0
            while inicio < fim:
                janela_fim = min(inicio + timedelta(days=janela_dias), fim)
                for registro in self._colher_janela(metadata_prefix, conjunto, inicio,
                                                    janela_fim, vistos, janela_minima_dias):
                    yield registro
                    emitidos += 1
                    if limite and emitidos >= limite:
                        return
                inicio = janela_fim
            return

        params: dict = {"verb": "ListRecords", "metadataPrefix": metadata_prefix}
        if conjunto:
            params["set"] = conjunto
        if desde:
            params["from"] = desde
        if ate:
            params["until"] = ate

        emitidos = 0
        while True:
            raiz = self._pedir(params)
            no = raiz.find("oai:ListRecords", NS)
            if no is None:
                return

            for registro in no.findall("oai:record", NS):
                cabecalho = registro.find("oai:header", NS)
                if cabecalho is not None and cabecalho.get("status") == "deleted":
                    continue
                yield registro
                emitidos += 1
                if limite and emitidos >= limite:
                    return
                if emitidos % 500 == 0:
                    log.info("OAI: %d registros colhidos", emitidos)

            token = (no.findtext("oai:resumptionToken", "", NS) or "").strip()
            if not token:
                return
            # resumptionToken é exclusivo: só ele e o verb.
            params = {"verb": "ListRecords", "resumptionToken": token}


def _texto_dc(no: ET.Element, campo: str) -> list[str]:
    return [(e.text or "").strip() for e in no.findall(f"dc:{campo}", NS) if (e.text or "").strip()]


def _parsear_oai_dc(registro: ET.Element, fonte: str,
                    endpoint_origem: str = "") -> RegistroInventario | None:
    cabecalho = registro.find("oai:header", NS)
    metadados = registro.find("oai:metadata/oai_dc:dc", NS)
    if metadados is None or cabecalho is None:
        return None

    identificador = (cabecalho.findtext("oai:identifier", "", NS) or "").strip()
    titulos = _texto_dc(metadados, "title")
    if not titulos:
        return None

    identificadores = _texto_dc(metadados, "identifier")
    handles = [i for i in identificadores if "handle" in i or i.startswith("http")]
    dois = [i for i in identificadores if "10." in i and "doi" in i.lower()]
    # oai_dc quase nunca entrega o binário; quando entrega, é um .pdf explícito
    binarios = [i for i in identificadores if i.lower().split("?")[0].endswith(".pdf")]

    datas = _texto_dc(metadados, "date")
    ano = None
    for d in datas:
        m = re.search(r"(19|20)\d{2}", d)
        if m:
            ano = int(m.group(0))
            break

    return RegistroInventario(
        fonte=fonte,
        chave_origem=identificador,
        titulo=titulos[0],
        autor="; ".join(_texto_dc(metadados, "creator")[:3]),
        ano=ano,
        ies="; ".join(_texto_dc(metadados, "publisher")[:2]),
        area="; ".join(_texto_dc(metadados, "subject")[:6]),
        taxonomia="dc.subject (livre)",
        tipo="; ".join(_texto_dc(metadados, "type")[:2]),
        idioma=(_texto_dc(metadados, "language") or [""])[0],
        identificador=(dois or handles or [""])[0],
        endpoint=endpoint_origem,
        url_landing=(handles or [""])[0],
        url_binario=(binarios or [""])[0],
        resumo=(_texto_dc(metadados, "description") or [""])[0],
        extra={"direitos": "; ".join(_texto_dc(metadados, "rights")[:3])},
    )


def _dim(no: ET.Element, elemento: str, qualificador: str | None = None,
         mdschema: str = "dc") -> list[str]:
    """
    Lê `<dim:field mdschema=... element=... qualifier=...>` do formato
    `metadataPrefix=dim`.

    `qualificador=None` pega só o campo SEM qualifier (ex.: `dc.publisher`,
    a instituição). `qualificador="*"` pega qualquer qualifier. Uma string
    pega o qualifier exato (ex.: `"program"` para `dc.publisher.program`).
    É essa distinção que `oai_dc` não preserva — instituição e programa
    colapsam no mesmo `<dc:publisher>` sem qualifier, e é por isso que
    `programa` chega vazio.
    """
    saida = []
    for campo in no.findall("dim:field", NS):
        if campo.get("mdschema") != mdschema or campo.get("element") != elemento:
            continue
        qual = campo.get("qualifier")
        if qualificador == "*":
            pass
        elif qualificador is None and qual:
            continue
        elif qualificador not in (None, "*") and qual != qualificador:
            continue
        texto = (campo.text or "").strip()
        if texto:
            saida.append(texto)
    return saida


def _parsear_dim(registro: ET.Element, fonte: str,
                  endpoint_origem: str = "") -> RegistroInventario | None:
    """
    metadataPrefix=dim. Repositórios brasileiros de TEDE/DSpace seguem o
    padrão em que `dc.publisher` (sem qualifier) é a instituição e
    `dc.publisher.program` é o programa de pós-graduação — o mesmo campo por
    trás da faceta `dc.publisher.program.fl_str_mv` da própria BDTD. Como
    `oai_dc` acha o qualifier, esse campo se perde nele.
    """
    cabecalho = registro.find("oai:header", NS)
    metadados = registro.find("oai:metadata/dim:dim", NS)
    if metadados is None or cabecalho is None:
        return None

    identificador = (cabecalho.findtext("oai:identifier", "", NS) or "").strip()
    titulos = _dim(metadados, "title")
    if not titulos:
        return None

    identificadores = _dim(metadados, "identifier", qualificador="*")
    handles = [i for i in identificadores if "handle" in i or i.startswith("http")]
    dois = [i for i in identificadores if "10." in i and "doi" in i.lower()]
    binarios = [i for i in identificadores if i.lower().split("?")[0].endswith(".pdf")]

    datas = _dim(metadados, "date", qualificador="*")
    ano = None
    for d in datas:
        m = re.search(r"(19|20)\d{2}", d)
        if m:
            ano = int(m.group(0))
            break

    # Na UFMG (e comum em DSpace brasileiro) o programa mora em
    # mdschema="local" element="publisher" qualifier="program" — não em
    # dc.publisher.program, que é o padrão só na teoria. Confirmado inspecionando
    # um GetRecord real (oai:repositorio.ufmg.br:1843/46851): dc.publisher só
    # tem a instituição; department/program/initials ficam todos em `local`.
    programa = (_dim(metadados, "publisher", qualificador="program")
                or _dim(metadados, "publisher", qualificador="program", mdschema="local")
                or _dim(metadados, "description", qualificador="program"))

    autores = _dim(metadados, "creator") or _dim(metadados, "contributor", qualificador="author")

    return RegistroInventario(
        fonte=fonte,
        chave_origem=identificador,
        titulo=titulos[0],
        autor="; ".join(autores[:3]),
        ano=ano,
        ies="; ".join(_dim(metadados, "publisher")[:2]),
        programa="; ".join(programa[:2]),
        area="; ".join(_dim(metadados, "subject", qualificador="*")[:6]),
        taxonomia="dc.subject (livre)",
        tipo="; ".join(_dim(metadados, "type", qualificador="*")[:2]),
        idioma=(_dim(metadados, "language", qualificador="*") or [""])[0],
        identificador=(dois or handles or [""])[0],
        endpoint=endpoint_origem,
        url_landing=(handles or [""])[0],
        url_binario=(binarios or [""])[0],
        # Mesma história do programa: o resumo em português muitas vezes só
        # existe em local.description.resumo; dc.description(.abstract) às
        # vezes só tem o abstract em inglês, ou nem existe.
        resumo=(_dim(metadados, "description", qualificador="abstract")
                or _dim(metadados, "description")
                or _dim(metadados, "description", qualificador="resumo", mdschema="local")
                or [""])[0],
        extra={"direitos": "; ".join(_dim(metadados, "rights", qualificador="*")[:3])},
    )


def _parsear_etdms(registro: ET.Element, fonte: str,
                    endpoint_origem: str = "") -> RegistroInventario | None:
    """
    metadataPrefix=etdms (ETD-MS, padrão internacional de teses e
    dissertações). O programa vem em `<thesis:degree><thesis:discipline>`,
    um elemento composto próprio do schema — não em `dc:*` qualificado como
    no `dim`.
    """
    cabecalho = registro.find("oai:header", NS)
    metadados = registro.find("oai:metadata/etdms:thesis", NS)
    if metadados is None or cabecalho is None:
        return None

    identificador = (cabecalho.findtext("oai:identifier", "", NS) or "").strip()
    titulos = _texto_dc(metadados, "title")
    if not titulos:
        return None

    identificadores = _texto_dc(metadados, "identifier")
    handles = [i for i in identificadores if "handle" in i or i.startswith("http")]
    dois = [i for i in identificadores if "10." in i and "doi" in i.lower()]
    binarios = [i for i in identificadores if i.lower().split("?")[0].endswith(".pdf")]

    datas = _texto_dc(metadados, "date")
    ano = None
    for d in datas:
        m = re.search(r"(19|20)\d{2}", d)
        if m:
            ano = int(m.group(0))
            break

    grau = metadados.find("etdms:degree", NS)
    programa = (grau.findtext("etdms:discipline", "", NS) or "").strip() if grau is not None else ""

    return RegistroInventario(
        fonte=fonte,
        chave_origem=identificador,
        titulo=titulos[0],
        autor="; ".join(_texto_dc(metadados, "creator")[:3]),
        ano=ano,
        ies="; ".join(_texto_dc(metadados, "publisher")[:2]),
        programa=programa,
        area="; ".join(_texto_dc(metadados, "subject")[:6]),
        taxonomia="dc.subject (livre)",
        tipo="; ".join(_texto_dc(metadados, "type")[:2]),
        idioma=(_texto_dc(metadados, "language") or [""])[0],
        identificador=(dois or handles or [""])[0],
        endpoint=endpoint_origem,
        url_landing=(handles or [""])[0],
        url_binario=(binarios or [""])[0],
        resumo=(_texto_dc(metadados, "description") or [""])[0],
        extra={
            "direitos": "; ".join(_texto_dc(metadados, "rights")[:3]),
            "grau_nome": (grau.findtext("etdms:name", "", NS) or "").strip() if grau is not None else "",
            "grau_orientador": (grau.findtext("etdms:grantor", "", NS) or "").strip() if grau is not None else "",
        },
    )


def _extrair_binarios_ore(registro: ET.Element) -> list[str]:
    """
    Extrai URLs de bitstream de uma resposta `metadataPrefix=ore`.

    O DSpace mudou o formato do ORE entre versões (RDF/XML numa, ATOM noutra),
    então em vez de casar com um schema específico varremos a árvore inteira
    atrás de atributos que apontem para arquivo. Feio, e resiliente.

    Isso importa por dois motivos. Técnico: dispensa raspar HTML da landing
    page. Ético: uma requisição OAI substitui uma requisição de página por
    documento, o que reduz a carga no servidor da universidade pela metade.
    """
    candidatos: list[tuple[int, str]] = []
    for elemento in registro.iter():
        tipo = (elemento.get("type") or "").lower()
        for atributo, valor in elemento.attrib.items():
            if not isinstance(valor, str) or not valor.startswith("http"):
                continue
            if not atributo.endswith(("href", "resource")):
                continue
            limpo = valor.split("?")[0].lower()
            if tipo == "application/pdf":
                prioridade = 0
            elif limpo.endswith(".pdf"):
                prioridade = 1
            elif "/bitstream" in limpo:
                prioridade = 2
            else:
                continue
            # Miniaturas e licenças não são o documento.
            if any(x in limpo for x in ("thumbnail", "license_rdf", "license.txt", ".jpg", ".png")):
                continue
            candidatos.append((prioridade, valor))

    vistos, saida = set(), []
    for _, url in sorted(candidatos, key=lambda c: c[0]):
        if url not in vistos:
            vistos.add(url)
            saida.append(url)
    return saida


CAMINHOS_OAI = [
    "/oai/request",          # DSpace 5/6 e TEDE (o mais comum no Brasil)
    "/server/oai/request",   # DSpace 7+
    "/oai",
    "/oai/driver",
    "/jspui/oai/request",
    "/dspace-oai/request",
    "/oai/openaire",
]


def enriquecer_ore(cfg: Config, registros: list[dict], prefixo: str = "ore") -> int:
    """
    Busca o bitstream via GetRecord apenas dos registros JÁ SELECIONADOS.

    Recebe dicts (o inventário já foi serializado) e escreve `url_binario`
    in-place. Agrupa por endpoint para reaproveitar sessão e rate limit.
    """
    por_endpoint: dict[str, list[dict]] = {}
    for r in registros:
        if r.get("url_binario") or not r.get("endpoint") or not r.get("chave_origem"):
            continue
        por_endpoint.setdefault(r["endpoint"], []).append(r)

    total = 0
    for endpoint, itens in por_endpoint.items():
        cliente = ClienteOAI(endpoint, cfg)
        casados, falhas = 0, 0
        for i, r in enumerate(itens, 1):
            try:
                registro = cliente.get_record(r["chave_origem"], prefixo)
            except Exception:
                falhas += 1
                if falhas > 20:
                    log.warning("ORE falhando em %s; abandonando", endpoint)
                    break
                continue
            if registro is None:
                continue
            urls = _extrair_binarios_ore(registro)
            if urls:
                r["url_binario"] = urls[0]
                casados += 1
            if i % 50 == 0:
                log.info("ORE %s: %d/%d, %d casados", endpoint, i, len(itens), casados)
        log.info("ORE %s: %d bitstreams em %d selecionados", endpoint, casados, len(itens))
        total += casados
    return total


def descobrir_endpoint(base: str, cfg: Config) -> dict:
    """
    Procura o endpoint OAI de um repositório testando as convenções conhecidas.

    Também consulta o robots.txt do domínio e lista os formatos disponíveis.
    A saída é o registro de evidência que vai para o protocolo de coleta:
    o que você testou, quando, e o que o servidor respondeu.
    """
    import urllib.parse
    import urllib.robotparser
    from datetime import datetime, timezone

    base = base.rstrip("/")
    partes = urllib.parse.urlsplit(base)
    dominio = f"{partes.scheme}://{partes.netloc}"

    resultado = {
        "base": base,
        "verificado_em": datetime.now(timezone.utc).isoformat(),
        "robots_txt": f"{dominio}/robots.txt",
        "robots_conteudo": "",
        "endpoint": None,
        "repositorio": "",
        "formatos": [],
        "tem_ore": False,
        "conjuntos_amostra": [],
        "tentativas": [],
    }

    try:
        resp = requests.get(
            resultado["robots_txt"],
            timeout=30,
            headers={"User-Agent": cfg.user_agent()},
        )
        if resp.status_code == 200:
            resultado["robots_conteudo"] = resp.text[:4000]
    except requests.RequestException as exc:
        resultado["robots_conteudo"] = f"(inacessível: {exc})"

    for caminho in CAMINHOS_OAI:
        url = base + caminho
        try:
            cliente = ClienteOAI(url, cfg)
            info = cliente.identify()
            if info.get("repositoryName") or info.get("baseURL"):
                resultado["endpoint"] = url
                resultado["repositorio"] = info.get("repositoryName", "")
                resultado["identify"] = info
                resultado["tentativas"].append({"url": url, "ok": True})
                formatos = cliente.list_metadata_formats()
                resultado["formatos"] = [f["prefix"] for f in formatos]
                resultado["tem_ore"] = "ore" in resultado["formatos"]
                try:
                    resultado["conjuntos_amostra"] = cliente.list_sets()[:40]
                except Exception:
                    pass
                return resultado
            resultado["tentativas"].append({"url": url, "ok": False, "erro": "sem Identify"})
        except Exception as exc:
            resultado["tentativas"].append({"url": url, "ok": False, "erro": str(exc)[:160]})

    return resultado


def colher_oai(cfg: Config, cfg_fonte: dict,
               janelas_perdidas: list | None = None) -> list[RegistroInventario]:
    endpoint = cfg_fonte["endpoint"]
    cliente = ClienteOAI(endpoint, cfg)
    fonte = f"oai:{re.sub(r'^https?://', '', endpoint).split('/')[0]}"

    info = cliente.identify()
    if info:
        log.info("OAI %s: %s", fonte, info.get("repositoryName", "?"))

    prefixo_md = cfg_fonte.get("metadata_prefix", "oai_dc")
    parser = {
        "oai_dc": _parsear_oai_dc,
        "dim": _parsear_dim,
        "etdms": _parsear_etdms,
    }.get(prefixo_md)
    if parser is None:
        log.warning("metadata_prefix %r sem parser dedicado; usando oai_dc", prefixo_md)
        parser = _parsear_oai_dc

    registros = []
    try:
        for registro in cliente.list_records(
            metadata_prefix=prefixo_md,
            conjunto=cfg_fonte.get("set"),
            desde=cfg_fonte.get("from"),
            ate=cfg_fonte.get("until"),
            limite=int(cfg_fonte.get("limite", 0)),
            janela_dias=int(cfg_fonte.get("janela_dias", 0)),
            janela_minima_dias=int(cfg_fonte.get("janela_minima_dias", 1)),
        ):
            item = parser(registro, fonte, endpoint)
            if item:
                registros.append(item)
    except Exception as exc:
        # Perder 7.900 registros já colhidos porque a paginação quebrou na
        # página 80 é desperdício puro — e obriga a bater no servidor de novo
        # para recuperar o que já estava na mão. Colheita parcial é resultado.
        log.warning("colheita interrompida em %s após %d registros: %s",
                    fonte, len(registros), exc)
        if not registros:
            raise
    if janelas_perdidas is not None:
        janelas_perdidas.extend(
            {"endpoint": endpoint, **j} for j in getattr(cliente, "janelas_perdidas", [])
        )

    # Filtro por assunto/tipo. Um repositório institucional inteiro tem de
    # tudo; você quer teses e dissertações de saúde.
    termos = [_normalizar_nome_coluna(t) for t in cfg_fonte.get("filtro_assunto", [])]
    if termos:
        antes = len(registros)
        registros = [
            r for r in registros
            if any(t in _normalizar_nome_coluna(f"{r.area} {r.titulo} {r.programa}") for t in termos)
        ]
        log.info("filtro de assunto: %d -> %d registros", antes, len(registros))

    # Exclusão explícita. Necessária porque inclusão por palavra é ambígua:
    # "medicina" casa com "Medicina Veterinária", que a CAPES classifica em
    # Ciências Agrárias e que o protocolo exclui da área Saúde.
    #
    # Inclui o resumo na checagem, não só área/título/programa: um termo como
    # "nutricao" no filtro de inclusão casa tanto com nutrição humana quanto
    # com nutrição animal, e teses de zootecnia raramente têm "zootecnia" no
    # título ou nas subject keywords — só aparece no corpo do resumo (ex.:
    # "bovinos de corte", "ovinos", "silagem"). Achado lendo o corpus real:
    # 14 documentos de zootecnia/produção animal passaram pelo filtro antigo.
    excluir = [_normalizar_nome_coluna(t) for t in cfg_fonte.get("excluir_assunto", [])]
    if excluir:
        antes = len(registros)
        registros = [
            r for r in registros
            if not bate_exclusao(f"{r.area} {r.titulo} {r.programa} {r.resumo}", excluir,
                                 cfg.get_path("escopo.expressoes_permitidas", []))
        ]
        log.info("exclusão de assunto: %d -> %d registros", antes, len(registros))

    termos_tipo = [_normalizar_nome_coluna(t) for t in cfg_fonte.get("filtro_tipo", [])]
    if termos_tipo:
        antes = len(registros)
        registros = [
            r for r in registros
            if any(t in _normalizar_nome_coluna(r.tipo) for t in termos_tipo)
        ]
        log.info("filtro de tipo: %d -> %d registros", antes, len(registros))

    # Segunda passada em ORE: traz o bitstream sem precisar raspar HTML.
    # Metade das requisições ao servidor da universidade, e nenhum parser
    # de página que quebra quando o repositório muda de tema.
    prefixo_bin = cfg_fonte.get("prefix_binarios")
    if cfg_fonte.get("adiar_ore", True):
        # ORE custa uma requisição POR REGISTRO. Rodá-la aqui, sobre tudo que
        # o filtro deixou passar, é desperdício: a amostragem vai descartar a
        # maior parte logo depois. Adiada para depois do sorteio, o custo cai
        # de "todos os candidatos" para "os que serão baixados" — e é isso que
        # torna viável colher o set inteiro (limite: 0) sem punir o servidor.
        com_binario = sum(1 for r in registros if r.url_binario)
        log.info("OAI %s: %d registros (ORE adiado para depois da amostragem)",
                 fonte, len(registros))
        return registros

    if prefixo_bin and registros:
        # GetRecord por identificador, um por documento SELECIONADO.
        #
        # A versão anterior varria o set inteiro com ListRecords e descartava
        # o que não interessava: para casar 72 documentos ela colhia 7.900
        # registros, ~160 requisições em vez de 72 — e morria com HTTP 500 na
        # paginação profunda, que é justamente onde o DSpace quebra.
        # Aqui o custo passa a ser proporcional ao que você quer, não ao
        # tamanho do repositório.
        casados, falhas = 0, 0
        for i, r in enumerate(registros, 1):
            if r.url_binario or not r.chave_origem:
                continue
            try:
                registro = cliente.get_record(r.chave_origem, prefixo_bin)
            except Exception as exc:
                falhas += 1
                if falhas <= 3:
                    log.debug("ORE falhou em %s: %s", r.chave_origem, exc)
                if falhas > 20:
                    log.warning("ORE falhando de forma persistente; abandonando a passada")
                    break
                continue
            if registro is None:
                continue
            urls = _extrair_binarios_ore(registro)
            if urls:
                r.url_binario = urls[0]
                casados += 1
            if i % 50 == 0:
                log.info("ORE: %d/%d consultados, %d casados", i, len(registros), casados)
        log.info("ORE: %d bitstreams casados em %d registros (%d falhas)",
                 casados, len(registros), falhas)

    com_binario = sum(1 for r in registros if r.url_binario)
    log.info(
        "OAI %s: %d registros, %d (%.1f%%) com link direto para o binário",
        fonte, len(registros), com_binario, 100 * com_binario / max(len(registros), 1),
    )
    return registros