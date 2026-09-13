"""
robots.txt lido pela letra E pelo espírito.

A letra é o `RobotFileParser.can_fetch` com o nosso User-Agent. O espírito é o
que a letra não pega — os dois casos reais do piloto de 2026-09-13:

  - veto nominal a robôs de IA (tede2.pucrs.br: `User-agent: GPTBot`,
    `ClaudeBot`, `CCBot`... com `Disallow: /`). Nosso User-Agent não está na
    lista, mas o uso deste corpus é treino de modelo: o repositório disse não;
  - página de desafio anti-robô no lugar do robots.txt (repositorio.ufsc.br,
    Cloudflare Turnstile): proteção ativa contra acesso automatizado.

Os dois tiram o domínio inteiro da coleta. Nada disso é contornado.
"""

from __future__ import annotations

import urllib.robotparser
from dataclasses import dataclass

ROBOS_DE_IA = {
    "gptbot", "chatgpt-user", "oai-searchbot", "claudebot", "claude-web", "anthropic-ai",
    "ccbot", "google-extended", "amazonbot", "applebot-extended", "bytespider",
    "meta-externalagent", "perplexitybot", "cohere-ai", "diffbot", "omgilibot",
}
_SINAIS_DESAFIO = ("cf-chl", "challenge-platform", "turnstile", "just a moment",
                   "checking your browser", "captcha", "attention required", "ddos-guard")
# Caminhos típicos de página de item e de arquivo (DSpace, JSPUI, DSpace 7, TEDE).
CAMINHOS_DE_ITEM = ("/handle/1/1", "/bitstream/1/1/tese.pdf", "/jspui/handle/1/1",
                    "/items/1", "/tde_busca/arquivo.php")


_SINAIS_DESAFIO_NA_PAGINA = (
    "cf-chl", "/cdn-cgi/challenge-platform", "<title>just a moment", "checking your browser",
    "attention required! | cloudflare", "ddos-guard", "não é um bot", "nao e um bot",
    "you are not a robot", "are you a robot",
)


def pagina_de_desafio(html: str) -> bool:
    """
    Página de item que é, na verdade, desafio anti-robô. Achado real na coleta
    até 20 mil: repositorio.fgv.br responde HTTP 200 com "Certificando de que
    você não é um bot!". Sinais mais estritos que os do robots.txt: página de
    item legítima pode ter reCAPTCHA num formulário ("pedir cópia").
    """
    amostra = (html or "")[:20000].lower()
    return any(sinal in amostra for sinal in _SINAIS_DESAFIO_NA_PAGINA)


@dataclass(frozen=True)
class Veredito:
    permitido: bool
    motivo: str
    crawl_delay: float | None = None


def _grupos(texto: str) -> list[tuple[set[str], list[str]]]:
    """Grupos `User-agent` → regras, como no RFC 9309."""
    grupos: list[tuple[set[str], list[str]]] = []
    agentes: set[str] = set()
    regras: list[str] = []
    em_regras = False
    for linha in texto.splitlines():
        linha = linha.split("#", 1)[0].strip()
        if ":" not in linha:
            continue
        campo, valor = (p.strip() for p in linha.split(":", 1))
        campo = campo.lower()
        if campo == "user-agent":
            if em_regras:
                grupos.append((agentes, regras))
                agentes, regras, em_regras = set(), [], False
            agentes.add(valor.lower().split("/")[0])
        elif campo in ("disallow", "allow"):
            em_regras = True
            regras.append(f"{campo}:{valor}")
    if agentes:
        grupos.append((agentes, regras))
    return grupos


def veta_robos_de_ia(texto: str) -> bool:
    """Qualquer `Disallow` não vazio num grupo que nomeia robô de IA é veto."""
    return any(agentes & ROBOS_DE_IA and any(r.startswith("disallow:") and r != "disallow:" for r in regras)
               for agentes, regras in _grupos(texto))


def classificar(status: int | None, texto: str, user_agent: str) -> Veredito:
    if status is None:
        return Veredito(False, "inacessivel")
    amostra = (texto or "")[:5000].lower()
    if any(sinal in amostra for sinal in _SINAIS_DESAFIO):
        return Veredito(False, "desafio_anti_robo")
    if status in (404, 410):
        return Veredito(True, "sem_robots")
    if status != 200:
        # 401/403: o padrão manda tratar como "tudo proibido"; 429/5xx: servidor
        # com problema, que é critério de parada do protocolo.
        return Veredito(False, f"http_{status}")
    if amostra.lstrip().startswith("<") or "<html" in amostra[:500]:
        # Site que devolve a própria página no lugar do robots.txt (comum em
        # DSpace 7 sem robots): não há regra escrita.
        return Veredito(True, "robots_html_sem_regras")
    if veta_robos_de_ia(texto):
        return Veredito(False, "veto_robos_ia")
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(texto.splitlines())
    if not any(rp.can_fetch(user_agent, caminho) for caminho in CAMINHOS_DE_ITEM):
        return Veredito(False, "bloqueia_nosso_agente")
    try:
        atraso = rp.crawl_delay(user_agent) or rp.crawl_delay("*")
    except Exception:
        atraso = None
    return Veredito(True, "ok", float(atraso) if atraso else None)
