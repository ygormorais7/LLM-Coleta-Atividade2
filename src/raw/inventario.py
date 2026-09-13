"""
ESTÁGIO 1 — reconciliação e amostragem.

Duas coisas que o plano tratava como uma linha e são, cada uma, um passo com
método próprio.

RECONCILIAÇÃO
=============
CAPES ∪ OpenAIRE ∪ LA Referencia vai contar a mesma tese 2-3 vezes. Só que
isso NÃO é um join por chave: os registros da CAPES praticamente nunca têm
handle ou DOI. A chave real é título + autor + ano + IES, e cada campo é sujo
de um jeito diferente:

  - acento, cedilha e caixa
  - subtítulo presente numa fonte e ausente na outra
  - ordem do nome ("Silva, João da" contra "João da Silva")
  - variantes de IES ("UFPI", "Universidade Federal do Piauí", "Univ. Fed. PI")
  - ano de defesa contra ano-base da coleta, que divergem com frequência

Portanto: record linkage com blocking, limiar e validação manual. O relatório
guarda uma amostra de pares aceitos e de pares rejeitados no limite, para você
olhar com o olho antes de confiar nas contagens por fonte do DATACARD.

AMOSTRAGEM
==========
A moldura CAPES tem não-resposta alta e NÃO uniforme: IES grandes com
repositório maduro resolvem bem; IES pequenas e anos antigos resolvem mal.
Sortear N e torcer produz corpus enviesado mesmo partindo de um plano
estratificado correto.

Por isso a amostragem aqui produz, para cada estrato, uma COTA e uma FILA DE
RESERVA ordenada. O harvest consome a fila até fechar a cota, e a taxa de
resolução por estrato é reportada como característica do corpus.

CLI:
    python -m src.raw.inventario construir
    python -m src.raw.inventario sets --endpoint https://api.openaire.eu/oai_pmh
    python -m src.raw.inventario identify --endpoint https://api.openaire.eu/oai_pmh
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from ..common import Config, Relatorio, configurar_log, escrever_jsonl, ler_jsonl
from . import fontes as fontes_mod

log = configurar_log("raw.inventario")

try:
    from rapidfuzz.fuzz import token_sort_ratio as _ratio_rapido
except ImportError:  # stdlib é suficiente, só mais lento
    _ratio_rapido = None

_ARTIGOS = {"a", "o", "as", "os", "um", "uma", "de", "da", "do", "das", "dos",
            "e", "em", "no", "na", "para", "com", "the", "of"}

# Só as mais comuns; complete conforme a sua área/região.
_SIGLAS_IES = {
    "universidade federal do piaui": "ufpi",
    "universidade federal do ceara": "ufc",
    "universidade de sao paulo": "usp",
    "universidade estadual de campinas": "unicamp",
    "universidade federal de minas gerais": "ufmg",
    "universidade federal do rio de janeiro": "ufrj",
    "universidade federal do rio grande do sul": "ufrgs",
    "universidade federal de pernambuco": "ufpe",
    "universidade federal da bahia": "ufba",
    "universidade estadual paulista": "unesp",
    "universidade federal de santa catarina": "ufsc",
    "universidade de brasilia": "unb",
    "universidade federal de sao paulo": "unifesp",
    "fundacao oswaldo cruz": "fiocruz",
}


def _ascii(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()


def norm_titulo(titulo: str) -> str:
    t = _ascii(titulo)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    palavras = [p for p in t.split() if p not in _ARTIGOS and len(p) > 1]
    return " ".join(palavras)


def norm_autor(autor: str) -> str:
    """'Silva, João da' e 'João da Silva' colapsam no mesmo conjunto ordenado."""
    a = _ascii(autor).replace(";", " ").replace(",", " ")
    partes = sorted(p for p in re.findall(r"[a-z]+", a) if p not in _ARTIGOS and len(p) > 1)
    return " ".join(partes)


def norm_ies(ies: str) -> str:
    i = re.sub(r"[^a-z ]+", " ", _ascii(ies))
    i = re.sub(r"\s+", " ", i).strip()
    for nome, sigla in _SIGLAS_IES.items():
        if nome in i:
            return sigla
    compacto = i.replace(" ", "")
    if 2 <= len(compacto) <= 8:
        return compacto
    iniciais = "".join(p[0] for p in i.split() if p not in _ARTIGOS)
    return iniciais or compacto[:8]


def _similaridade(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if _ratio_rapido is not None:
        return _ratio_rapido(a, b) / 100.0
    return SequenceMatcher(None, a, b).ratio()


def _bloco(reg: dict) -> str:
    """
    Chave de blocking: primeiras palavras do título + ano ±1.

    Blocking existe para não comparar N² pares. O ano entra com tolerância
    porque ano-base da CAPES e ano de defesa divergem com frequência —
    por isso cada registro gera até três blocos.
    """
    titulo = norm_titulo(reg.get("titulo", ""))
    return " ".join(titulo.split()[:4]) or "sem-titulo"


def reconciliar(
    registros: list[dict],
    limiar: float = 0.90,
    limiar_revisao: float = 0.82,
    rel: Relatorio | None = None,
) -> tuple[list[dict], dict]:
    """
    Agrupa registros que descrevem o mesmo trabalho e devolve um por grupo,
    com a proveniência de todas as fontes que o continham.
    """
    indexados = list(enumerate(registros))
    blocos: dict[tuple[str, int | str], list[int]] = defaultdict(list)

    for i, reg in indexados:
        chave_titulo = _bloco(reg)
        ano = reg.get("ano")
        anos = [ano - 1, ano, ano + 1] if isinstance(ano, int) else ["?"]
        for a in anos:
            blocos[(chave_titulo, a)].append(i)

    pai = list(range(len(registros)))

    def raiz(x: int) -> int:
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    pares_aceitos, pares_limitrofes = [], []
    comparados: set[tuple[int, int]] = set()

    for indices in blocos.values():
        if len(indices) < 2 or len(indices) > 400:   # bloco gigante = chave ruim
            continue
        for pos_a in range(len(indices)):
            for pos_b in range(pos_a + 1, len(indices)):
                i, j = sorted((indices[pos_a], indices[pos_b]))
                if (i, j) in comparados:
                    continue
                comparados.add((i, j))
                a, b = registros[i], registros[j]

                # Handle/DOI iguais fecham o caso sem heurística.
                id_a, id_b = a.get("identificador", ""), b.get("identificador", "")
                if id_a and id_a == id_b:
                    score = 1.0
                else:
                    s_tit = _similaridade(norm_titulo(a.get("titulo", "")),
                                          norm_titulo(b.get("titulo", "")))
                    s_aut = _similaridade(norm_autor(a.get("autor", "")),
                                          norm_autor(b.get("autor", "")))
                    mesma_ies = norm_ies(a.get("ies", "")) == norm_ies(b.get("ies", ""))
                    score = 0.60 * s_tit + 0.30 * s_aut + 0.10 * (1.0 if mesma_ies else 0.0)

                if score >= limiar:
                    ra, rb = raiz(i), raiz(j)
                    if ra != rb:
                        pai[max(ra, rb)] = min(ra, rb)
                    if len(pares_aceitos) < 40:
                        pares_aceitos.append(
                            {"score": round(score, 3),
                             "a": a.get("titulo", "")[:110], "fonte_a": a.get("fonte"),
                             "b": b.get("titulo", "")[:110], "fonte_b": b.get("fonte")}
                        )
                elif score >= limiar_revisao and len(pares_limitrofes) < 40:
                    pares_limitrofes.append(
                        {"score": round(score, 3),
                         "a": a.get("titulo", "")[:110], "fonte_a": a.get("fonte"),
                         "b": b.get("titulo", "")[:110], "fonte_b": b.get("fonte")}
                    )

    grupos: dict[int, list[int]] = defaultdict(list)
    for i in range(len(registros)):
        grupos[raiz(i)].append(i)

    # Representante: quem tem link para o texto. Sem link, o corpus não existe.
    def pontuacao(idx: int) -> tuple:
        r = registros[idx]
        return (bool(r.get("url_binario")), bool(r.get("url_landing")),
                bool(r.get("identificador")), len(r.get("resumo", "")))

    fundidos = []
    for indices in grupos.values():
        principal = max(indices, key=pontuacao)
        base = dict(registros[principal])
        base["fontes"] = sorted({registros[i].get("fonte", "?") for i in indices})
        base["n_fontes"] = len(base["fontes"])
        # completa campos vazios com o que as outras fontes têm
        for i in indices:
            for campo in ("url_landing", "url_binario", "identificador", "resumo",
                          "programa", "ies", "area", "taxonomia", "tipo", "autor"):
                if not base.get(campo) and registros[i].get(campo):
                    base[campo] = registros[i][campo]
        fundidos.append(base)

    metricas = {
        "registros_entrada": len(registros),
        "registros_apos_reconciliacao": len(fundidos),
        "grupos_multifonte": sum(1 for f in fundidos if f["n_fontes"] > 1),
        "pares_comparados": len(comparados),
        "limiar": limiar,
        "amostra_pares_aceitos": pares_aceitos,
        "amostra_pares_limitrofes": pares_limitrofes,
    }
    log.info(
        "reconciliação: %d -> %d registros (%d com 2+ fontes), %d pares comparados",
        len(registros), len(fundidos), metricas["grupos_multifonte"], len(comparados),
    )
    log.info("REVISE À MÃO as amostras de pares no relatório antes de confiar nas contagens")
    if rel:
        rel.metricas["reconciliacao"] = metricas
    return fundidos, metricas


# ==========================================================================
# Amostragem
# ==========================================================================
def _faixa_ano(ano) -> str:
    if not isinstance(ano, int):
        return "sem-ano"
    return f"{(ano // 5) * 5}-{(ano // 5) * 5 + 4}"


def amostrar(
    registros: list[dict],
    n_alvo: int,
    estratos: list[str],
    semente: int = 42,
    fator_reserva: float = 4.0,
) -> tuple[list[dict], dict]:
    """
    Amostragem estratificada proporcional COM FILA DE RESERVA.

    A fila é a peça que faz diferença: como a não-resposta varia por estrato,
    o harvest precisa poder puxar substitutos DENTRO DO MESMO ESTRATO até
    fechar a cota. Sem isso, os estratos com repositório fraco encolhem
    sozinhos e o corpus fica enviesado sem ninguém perceber.
    """
    rng = pd.Series(range(len(registros))).sample(frac=1.0, random_state=semente).tolist()
    embaralhados = [registros[i] for i in rng]

    def chave(reg: dict) -> str:
        partes = []
        for e in estratos:
            if e == "ies":
                partes.append(norm_ies(reg.get("ies", "")))
            elif e in ("ano_faixa", "ano"):
                partes.append(_faixa_ano(reg.get("ano")))
            else:
                partes.append(_ascii(str(reg.get(e, "")))[:40] or "?")
        return "|".join(partes)

    por_estrato: dict[str, list[dict]] = defaultdict(list)
    for reg in embaralhados:
        por_estrato[chave(reg)].append(reg)

    total = len(embaralhados)
    saida: list[dict] = []
    resumo_estratos = {}

    for nome, itens in sorted(por_estrato.items()):
        proporcao = len(itens) / total
        cota = max(1, round(n_alvo * proporcao))
        limite_fila = min(len(itens), int(cota * fator_reserva))
        for ordem, reg in enumerate(itens[:limite_fila]):
            item = dict(reg)
            item["estrato"] = nome
            item["cota_estrato"] = cota
            item["ordem_na_fila"] = ordem
            item["na_cota_inicial"] = ordem < cota
            saida.append(item)
        resumo_estratos[nome] = {
            "populacao": len(itens),
            "cota": cota,
            "fila": limite_fila,
        }

    metricas = {
        "n_alvo": n_alvo,
        "estratos": estratos,
        "n_estratos": len(por_estrato),
        "candidatos_na_fila": len(saida),
        "na_cota_inicial": sum(1 for s in saida if s["na_cota_inicial"]),
        "fator_reserva": fator_reserva,
        "detalhe_estratos": dict(list(resumo_estratos.items())[:60]),
    }
    log.info(
        "amostragem: alvo %d, %d estratos, fila de %d candidatos (reserva %.0fx)",
        n_alvo, len(por_estrato), len(saida), fator_reserva,
    )
    return saida, metricas


# ==========================================================================
# Construção do inventário
# ==========================================================================
def construir(cfg: Config) -> Relatorio:
    rel = Relatorio(camada="inventario", area=cfg.get_path("projeto.area_rotulo", ""))
    dir_raw = cfg.dir_camada("raw")
    cfg_inv = cfg.get_path("inventario", {}) or {}

    brutos: list[dict] = []

    cfg_capes = cfg_inv.get("fontes", {}).get("capes", {})
    if cfg_capes.get("habilitada"):
        arquivos: list[Path] = []
        for padrao in cfg_capes.get("arquivos", []):
            arquivos.extend(sorted(Path().glob(padrao)))
        if not arquivos:
            rel.falha("capes", "sem_arquivos",
                      "baixe os CSV em dadosabertos.capes.gov.br e ajuste inventario.fontes.capes.arquivos")
        for reg in fontes_mod.ler_capes(
            arquivos,
            campo_area=cfg_capes.get("campo_area", "area_avaliacao"),
            valores_area=cfg_capes.get("valores_area", []),
        ):
            brutos.append(reg.para_dict())

    janelas_perdidas: list[dict] = []
    for cfg_oai in cfg_inv.get("fontes", {}).get("oai", []) or []:
        if not cfg_oai.get("habilitada", True):
            continue
        try:
            for reg in fontes_mod.colher_oai(cfg, cfg_oai, janelas_perdidas=janelas_perdidas):
                brutos.append(reg.para_dict())
        except Exception as exc:
            rel.falha(cfg_oai.get("endpoint", "?"), "oai_falhou", str(exc))
            log.error("OAI %s falhou: %s", cfg_oai.get("endpoint"), exc)
    for janela in janelas_perdidas:
        rel.falha(janela["endpoint"], "janela_oai_perdida",
                  f"{janela['de']}..{janela['ate']}: {janela['erro']}")
    rel.metricas["janelas_oai_perdidas"] = janelas_perdidas

    rel.entradas["registros_brutos"] = len(brutos)
    rel.entradas["por_fonte"] = dict(
        pd.Series([b["fonte"] for b in brutos]).value_counts()
    ) if brutos else {}

    if not brutos:
        rel.falha("inventario", "vazio", "nenhuma fonte produziu registros")
        rel.salvar(cfg.dir_relatorios())
        return rel

    cfg_rec = cfg_inv.get("reconciliacao", {}) or {}
    fundidos, _ = reconciliar(
        brutos,
        limiar=float(cfg_rec.get("limiar", 0.90)),
        limiar_revisao=float(cfg_rec.get("limiar_revisao", 0.82)),
        rel=rel,
    )

    cfg_am = cfg_inv.get("amostragem", {}) or {}
    amostra, metricas_am = amostrar(
        fundidos,
        n_alvo=int(cfg_am.get("n_alvo", 4000)),
        estratos=cfg_am.get("estratos", ["ies", "ano_faixa"]),
        semente=int(cfg_am.get("semente", 42)),
        fator_reserva=float(cfg_am.get("fator_reserva", 4.0)),
    )
    rel.metricas["amostragem"] = metricas_am

    # ORE só agora, sobre quem foi sorteado.
    prefixos = {f.get("prefix_binarios") for f in
                (cfg_inv.get("fontes", {}).get("oai", []) or []) if f.get("prefix_binarios")}
    if prefixos:
        casados = fontes_mod.enriquecer_ore(cfg, amostra, sorted(prefixos)[0])
        rel.metricas["bitstreams_via_ore"] = casados

    # Sem link para o texto, o registro serve para metadado e benchmark,
    # nunca para pré-treino. Fica marcado, não descartado.
    sem_link = sum(1 for a in amostra if not (a.get("url_landing") or a.get("url_binario")))
    rel.metricas["candidatos_sem_link"] = sem_link
    rel.metricas["prop_candidatos_sem_link"] = round(sem_link / max(len(amostra), 1), 4)

    destino = dir_raw / "inventario.jsonl"
    escrever_jsonl(destino, amostra)
    rel.saidas["inventario"] = str(destino)
    rel.saidas["candidatos"] = len(amostra)
    rel.parametros["taxonomia_declarada"] = cfg_inv.get("taxonomia", "NÃO DECLARADA")

    if rel.parametros["taxonomia_declarada"] == "NÃO DECLARADA":
        rel.falha("inventario", "taxonomia_nao_declarada",
                  "defina inventario.taxonomia — sem isso o escopo do corpus é indefinido")

    log.info("inventário gravado em %s (%d candidatos)", destino, len(amostra))
    rel.salvar(cfg.dir_relatorios())
    return rel


# ==========================================================================
# Recuperação de uma janela de colheita que falhou
# ==========================================================================
def _chave_estrato(reg: dict, estratos: list[str]) -> str:
    partes = []
    for e in estratos:
        if e == "ies":
            partes.append(norm_ies(reg.get("ies", "")))
        elif e in ("ano_faixa", "ano"):
            partes.append(_faixa_ano(reg.get("ano")))
        else:
            partes.append(_ascii(str(reg.get(e, "")))[:40] or "?")
    return "|".join(partes)


def mesclar_candidatos(existentes: list[dict], novos: list[dict],
                       estratos: list[str]) -> tuple[list[dict], list[dict]]:
    """
    Junta ao inventário candidatos colhidos numa janela recuperada, sem
    reamostrar: quem já estava fica onde estava; quem é novo entra no fim da
    fila do seu estrato, e a cota do estrato cresce na mesma medida — senão o
    harvest para ao fechar a cota antiga e nunca chega neles.
    Devolve (inventário mesclado, candidatos adicionados).
    """
    mesclado = [dict(c) for c in existentes]
    chaves = {c.get("chave_origem") for c in mesclado}
    ultima_ordem: dict[str, int] = defaultdict(lambda: -1)
    for c in mesclado:
        nome = c.get("estrato", "?")
        ultima_ordem[nome] = max(ultima_ordem[nome], int(c.get("ordem_na_fila") or 0))

    adicionados: list[dict] = []
    for reg in novos:
        if not reg.get("chave_origem") or reg["chave_origem"] in chaves:
            continue
        chaves.add(reg["chave_origem"])
        nome = _chave_estrato(reg, estratos)
        ultima_ordem[nome] += 1
        item = {**reg, "estrato": nome, "ordem_na_fila": ultima_ordem[nome], "na_cota_inicial": False}
        mesclado.append(item)
        adicionados.append(item)

    cota_antiga: dict[str, int] = defaultdict(int)
    for c in existentes:
        nome = c.get("estrato", "?")
        cota_antiga[nome] = max(cota_antiga[nome], int(c.get("cota_estrato") or 0))
    novos_por_estrato: dict[str, int] = defaultdict(int)
    for item in adicionados:
        novos_por_estrato[item["estrato"]] += 1
    for c in mesclado:
        nome = c.get("estrato")
        if nome in novos_por_estrato:
            c["cota_estrato"] = cota_antiga.get(nome, 0) + novos_por_estrato[nome]
    return mesclado, adicionados


def recolher_janela(cfg: Config, de: str, ate: str) -> Relatorio:
    """
    Recolhe só um intervalo de datestamp das fontes OAI habilitadas e junta ao
    inventário atual os candidatos que faltavam, sem refazer a colheita inteira.
    O inventário anterior é copiado antes de ser regravado.
    """
    import shutil

    rel = Relatorio(camada="inventario_janela", area=cfg.get_path("projeto.area_rotulo", ""))
    destino = cfg.dir_camada("raw") / "inventario.jsonl"
    existentes = list(ler_jsonl(destino))
    cfg_inv = cfg.get_path("inventario", {}) or {}
    estratos = (cfg_inv.get("amostragem", {}) or {}).get("estratos", ["ies", "ano_faixa"])
    rel.parametros.update({"de": de, "ate": ate})
    rel.entradas["candidatos_no_inventario"] = len(existentes)

    colhidos: list[dict] = []
    perdidas: list[dict] = []
    fontes_oai = [f for f in (cfg_inv.get("fontes", {}).get("oai", []) or []) if f.get("habilitada", True)]
    rel.parametros["metadata_prefix"] = sorted({f.get("metadata_prefix", "oai_dc") for f in fontes_oai})
    for cfg_oai in fontes_oai:
        janela = {**cfg_oai, "from": de, "until": ate, "adiar_ore": True}
        colhidos.extend(r.para_dict() for r in
                        fontes_mod.colher_oai(cfg, janela, janelas_perdidas=perdidas))

    mesclado, adicionados = mesclar_candidatos(existentes, colhidos, estratos)
    prefixos = {f.get("prefix_binarios") for f in fontes_oai if f.get("prefix_binarios")}
    if adicionados and prefixos:
        rel.metricas["bitstreams_via_ore"] = fontes_mod.enriquecer_ore(cfg, adicionados, sorted(prefixos)[0])
    if adicionados:
        shutil.copy2(destino, destino.with_name(f"inventario.antes_janela_{de}_{ate}.jsonl"))
        escrever_jsonl(destino, mesclado)

    rel.saidas.update({
        "saude_colhidos_na_janela": len(colhidos),
        "ja_estavam_no_inventario": len(colhidos) - len(adicionados),
        "novos_candidatos": len(adicionados),
        "inventario": str(destino),
    })
    for janela in perdidas:
        rel.falha(janela["endpoint"], "janela_oai_perdida",
                  f"{janela['de']}..{janela['ate']}: {janela['erro']}")
    rel.metricas["janelas_oai_perdidas"] = perdidas
    log.info("janela %s..%s: %d de Saúde colhidos, %d novos, %d subjanelas perdidas",
             de, ate, len(colhidos), len(adicionados), len(perdidas))
    rel.salvar(cfg.dir_relatorios())
    return rel


# ==========================================================================
# Inventário da BDTD exportado pelo grupo
# ==========================================================================
def _termos_exclusao_oai(cfg_inv: dict) -> list[str]:
    termos: list[str] = []
    for fonte in cfg_inv.get("fontes", {}).get("oai", []) or []:
        termos.extend(fonte.get("excluir_assunto", []) or [])
    return termos


def _dominio(url: str) -> str:
    import urllib.parse

    partes = urllib.parse.urlsplit(url or "")
    return f"{partes.scheme}://{partes.netloc}"


def vereditos_robots(cfg: Config) -> dict:
    """
    Veredito (`robots.classificar`) de cada `evidencia_robots_*.json`, por
    domínio com esquema (`https://repositorio.ufrn.br`). Evidência antiga, sem
    veredito gravado, é classificada de novo a partir do conteúdo.
    """
    import json

    from . import robots as robots_mod

    vereditos = {}
    for caminho in sorted(cfg.dir_relatorios().glob("evidencia_robots_*.json")):
        try:
            evidencia = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not evidencia.get("dominio"):
            continue
        vereditos[evidencia["dominio"].rstrip("/")] = robots_mod.classificar(
            evidencia.get("status_http"), evidencia.get("conteudo") or "", cfg.user_agent())
    return vereditos


def candidatos_bdtd(cfg: Config, aplicar_robots: bool = False) -> list[dict]:
    from ..common import RAIZ

    cfg_inv = cfg.get_path("inventario", {}) or {}
    cfg_fonte = cfg_inv.get("fontes", {}).get("bdtd_csv", {}) or {}
    candidatos = [r.para_dict() for r in fontes_mod.ler_inventario_bdtd(
        RAIZ / cfg_fonte["arquivo"], cfg_fonte, excluir_extra=_termos_exclusao_oai(cfg_inv),
        permitidas=cfg.get_path("escopo.expressoes_permitidas", []))]
    if not aplicar_robots:
        return candidatos
    vereditos = vereditos_robots(cfg)
    return [c for c in candidatos
            if vereditos.get(_dominio(c["url_landing"])) is None or vereditos[_dominio(c["url_landing"])].permitido]


def adicionar_inventario_bdtd(cfg: Config) -> Relatorio:
    """
    Junta ao inventário atual os candidatos do inventário da BDTD exportado pelo
    grupo, filtrados pelo escopo deste projeto, sem recolher as fontes OAI. O
    inventário anterior é copiado antes de ser regravado.
    """
    import shutil

    rel = Relatorio(camada="inventario_bdtd", area=cfg.get_path("projeto.area_rotulo", ""))
    cfg_fonte = cfg.get_path("inventario.fontes.bdtd_csv", {}) or {}
    if not cfg_fonte.get("habilitada"):
        rel.falha("bdtd_csv", "fonte_desabilitada", "habilite inventario.fontes.bdtd_csv no config")
        rel.salvar(cfg.dir_relatorios())
        return rel

    import collections
    from datetime import datetime

    destino = cfg.dir_camada("raw") / "inventario.jsonl"
    existentes = list(ler_jsonl(destino))
    estratos = (cfg.get_path("inventario.amostragem.estratos") or ["ies", "ano_faixa"])

    # Domínio cujo robots.txt não autoriza (veto a robôs de IA, desafio
    # anti-robô, bloqueio, servidor com erro) sai do inventário — inclusive
    # candidatos que já estavam lá de uma rodada anterior.
    vereditos = vereditos_robots(cfg)

    def _vetado(candidato: dict) -> bool:
        veredito = vereditos.get(_dominio(candidato.get("url_landing") or ""))
        return veredito is not None and not veredito.permitido

    retirados = [c for c in existentes if c.get("fonte") == "bdtd_inventario" and _vetado(c)]
    existentes = [c for c in existentes if not (c.get("fonte") == "bdtd_inventario" and _vetado(c))]
    todos = candidatos_bdtd(cfg)
    novos = [c for c in todos if not _vetado(c)]
    excluidos = collections.Counter(_dominio(c["url_landing"]) for c in todos if _vetado(c))
    mesclado, adicionados = mesclar_candidatos(existentes, novos, estratos)
    if adicionados or retirados:
        if destino.exists():
            carimbo = datetime.now().strftime("%Y%m%d_%H%M")
            shutil.copy2(destino, destino.with_name(f"inventario.antes_bdtd_csv_{carimbo}.jsonl"))
        escrever_jsonl(destino, mesclado)
    rel.saidas["dominios_excluidos_robots"] = {
        d: {"motivo": vereditos[d].motivo, "candidatos": n} for d, n in excluidos.most_common()}
    rel.saidas["retirados_do_inventario_por_robots"] = len(retirados)
    if excluidos:
        log.warning("inventário BDTD: %d domínio(s) fora pelo robots.txt: %s", len(excluidos),
                    ", ".join(f"{d} ({vereditos[d].motivo})" for d in sorted(excluidos)))

    dominios = pd.Series([re.sub(r"^https?://", "", a["url_landing"]).split("/")[0]
                          for a in adicionados], dtype=str)
    rel.parametros.update({k: cfg_fonte.get(k) for k in (
        "arquivo", "instituicoes", "excluir_instituicoes", "limite_por_instituicao", "filtro_assunto")})
    rel.entradas["candidatos_no_inventario"] = len(existentes)
    rel.saidas.update({
        "candidatos_depois_dos_filtros": len(novos),
        "novos_candidatos": len(adicionados),
        "por_instituicao": pd.Series([a["ies"] for a in adicionados], dtype=str).value_counts().to_dict(),
        "por_dominio": dominios.value_counts().to_dict(),
        "inventario": str(destino),
    })
    log.info("inventário BDTD: %d candidatos filtrados, %d novos no inventário", len(novos), len(adicionados))
    rel.salvar(cfg.dir_relatorios())
    return rel


def registrar_robots(cfg: Config, urls: list[str]) -> list[Path]:
    """
    Guarda o robots.txt de cada domínio como evidência para o protocolo: uma
    requisição por domínio. Link hdl.handle.net só registra o próprio
    hdl.handle.net — o domínio final é checado ao vivo pelo resolvedor.
    """
    import json
    import urllib.parse
    from datetime import datetime, timezone

    import requests

    from . import robots as robots_mod

    dominios = sorted({f"{p.scheme}://{p.netloc}" for p in map(urllib.parse.urlsplit, urls)
                       if p.netloc and not fontes_mod.host_interno(p.geturl())})
    salvos: list[Path] = []
    for dominio in dominios:
        try:
            resp = requests.get(f"{dominio}/robots.txt", timeout=30,
                                headers={"User-Agent": cfg.user_agent()})
            # Conteúdo inteiro: a lista de robôs de IA vetados costuma vir no fim
            # (antes guardávamos só os primeiros 4.000 caracteres).
            status, conteudo = resp.status_code, resp.text[:200_000]
        except requests.RequestException as exc:
            status, conteudo = None, f"(inacessível: {exc})"
        veredito = robots_mod.classificar(status, conteudo if status is not None else "", cfg.user_agent())
        destino = cfg.dir_relatorios() / f"evidencia_robots_{re.sub(r'[^a-z0-9]+', '_', dominio.lower())}.json"
        destino.write_text(json.dumps({
            "dominio": dominio, "robots_txt": f"{dominio}/robots.txt", "status_http": status,
            "conteudo": conteudo, "verificado_em": datetime.now(timezone.utc).isoformat(),
            "veredito": {"permitido": veredito.permitido, "motivo": veredito.motivo,
                         "crawl_delay": veredito.crawl_delay},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("robots.txt de %s: HTTP %s → %s", dominio, status, veredito.motivo)
        salvos.append(destino)
    return salvos


# ------------------------------------------------------------------- CLI
def _cli() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Inventário (Estágio 1)")
    ap.add_argument("comando", choices=["construir", "janela", "bdtd_csv", "robots",
                                        "identify", "sets", "formatos", "descobrir"])
    ap.add_argument("--endpoint", default="https://api.openaire.eu/oai_pmh")
    ap.add_argument("--base", default=None, help="URL base do repositório, para `descobrir`")
    ap.add_argument("--salvar", default=None, help="grava a evidência em JSON")
    ap.add_argument("--de", default=None, help="início (AAAA-MM-DD) da janela, para `janela`")
    ap.add_argument("--ate", default=None, help="fim (AAAA-MM-DD) da janela, para `janela`")
    ap.add_argument("--prefixo", default=None,
                    help="metadataPrefix só para `janela` (ex.: oai_dc quando o dim falha no servidor)")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = Config.carregar(args.config)

    if args.comando == "construir":
        construir(cfg)
        return

    if args.comando == "janela":
        if not (args.de and args.ate):
            ap.error("--de e --ate são obrigatórios para `janela`")
        if args.prefixo:
            # Na UFMG, 2026-02-25..2026-06-25 dá HTTP 500 só com dim; oai_dc responde
            # (sem o campo programa). Diagnóstico em data/reports/saude/diagnostico_janela_ufmg.json.
            for fonte in cfg.get_path("inventario.fontes.oai", []) or []:
                fonte["metadata_prefix"] = args.prefixo
        recolher_janela(cfg, args.de, args.ate)
        return

    if args.comando == "bdtd_csv":
        adicionar_inventario_bdtd(cfg)
        return

    if args.comando == "robots":
        registrar_robots(cfg, [c["url_landing"] for c in candidatos_bdtd(cfg)])
        return

    if args.comando == "descobrir":
        if not args.base:
            ap.error("--base é obrigatório para `descobrir`")
        resultado = fontes_mod.descobrir_endpoint(args.base, cfg)
        print(f"\nbase:        {resultado['base']}")
        print(f"endpoint:    {resultado['endpoint'] or 'NÃO ENCONTRADO'}")
        print(f"repositório: {resultado['repositorio']}")
        print(f"formatos:    {', '.join(resultado['formatos']) or '-'}")
        print(f"tem ORE:     {'SIM (bitstream direto, sem raspar HTML)' if resultado['tem_ore'] else 'não'}")
        if resultado["conjuntos_amostra"]:
            print("\nconjuntos (primeiros 40):")
            for spec, nome in resultado["conjuntos_amostra"]:
                print(f"  {spec:<45} {nome}")
        print("\n--- robots.txt ---")
        print(resultado["robots_conteudo"] or "(vazio)")
        destino = Path(args.salvar) if args.salvar else (
            cfg.dir_relatorios() / f"evidencia_{re.sub(r'[^a-z0-9]+', '_', args.base.lower())}.json"
        )
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nevidência salva em {destino}")
        print("Anexe este arquivo ao docs/PROTOCOLO_DE_COLETA.md.")
        return

    cliente = fontes_mod.ClienteOAI(args.endpoint, cfg)
    if args.comando == "identify":
        print(json.dumps(cliente.identify(), ensure_ascii=False, indent=2))
    elif args.comando == "formatos":
        for f in cliente.list_metadata_formats():
            print(f"{f['prefix']:<20} {f['schema']}")
    else:
        for spec, nome in cliente.list_sets():
            print(f"{spec:<50} {nome}")


if __name__ == "__main__":
    _cli()
