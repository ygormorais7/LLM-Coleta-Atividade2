"""
Segundo salto da coleta: da BDTD para o repositório da universidade.

A BDTD guarda metadado, não PDF. Cada registro traz a URL da página do
trabalho no repositório de origem (DSpace, TEDE, Lume, Pergamum...). Este
módulo resolve essa página até o arquivo e baixa os bytes.

Ordem de tentativas (da mais confiável para a mais frágil):

1. `<meta name="citation_pdf_url">` — tag Highwire Press. DSpace e TEDE
   emitem isso por padrão justamente para indexação pelo Google Scholar.
   É o caminho mais estável e o que quebra menos quando o tema do
   repositório muda.
2. `<meta name="eprints.document_url">` / `<meta name="DC.identifier">`.
3. Âncoras para /bitstream/ ou /bitstreams/ terminando em .pdf.
4. Qualquer <a href> .pdf na página, preferindo o maior/primeiro.
5. Selenium (opcional) para repositórios que montam o link via JavaScript.

Boas práticas embutidas, que é o que separa um crawler de um ataque de
negação de serviço acidental:
  - robots.txt consultado e respeitado por domínio;
  - rate limit POR DOMÍNIO (não global) — 30 universidades diferentes não
    precisam esperar umas pelas outras, mas cada uma recebe no máximo
    1 requisição a cada 3s;
  - User-Agent identificando projeto e e-mail de contato;
  - verificação de Content-Type e de magic bytes (%PDF) antes de salvar;
  - teto de tamanho, para não baixar um arquivo de 2 GB por engano;
  - download idempotente: se o arquivo já existe e o hash bate, pula.
"""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ..common import Config, RateLimiter, configurar_log, sha256_arquivo
from . import robots as robots_mod

log = configurar_log("raw.fulltext")

CABECALHOS_PDF = (b"%PDF",)
META_PDF = [
    ("meta", {"name": "citation_pdf_url"}),
    ("meta", {"name": "citation_fulltext_html_url"}),
    ("meta", {"name": "eprints.document_url"}),
    ("meta", {"property": "citation_pdf_url"}),
]


_HOSTS_INTERNOS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _no_mesmo_site(url: str, url_pagina: str) -> str:
    """
    Metatag com endereço interno do servidor vira endereço do site público.
    Achado real: o DSpace 7 da Fiocruz publica
    `citation_pdf_url = http://localhost:4000/bitstreams/<uuid>/download`
    (a renderização no servidor não conhece o próprio domínio).
    """
    partes = urllib.parse.urlsplit(url)
    pagina = urllib.parse.urlsplit(url_pagina)
    host = partes.hostname or ""
    interno = host in _HOSTS_INTERNOS
    if not interno and host != (pagina.hostname or ""):
        # Mesmo defeito com o IP do servidor e a porta do Angular: repositorio.uepb.edu.br
        # publica `http://200.129.73.159:4000/bitstreams/<uuid>/download`.
        try:
            ipaddress.ip_address(host)
            interno = True
        except ValueError:
            interno = partes.port == 4000
    if not interno:
        return url
    return urllib.parse.urlunsplit((pagina.scheme, pagina.netloc, partes.path, partes.query, ""))


def _sem_barra_dupla(url: str) -> str:
    """`https://www.bdtd.ueg.br//handle/tede/89` dá 404; com uma barra, abre."""
    partes = urllib.parse.urlsplit(url)
    caminho = re.sub(r"/{2,}", "/", partes.path)
    if caminho == partes.path:
        return url
    return urllib.parse.urlunsplit((partes.scheme, partes.netloc, caminho, partes.query, partes.fragment))


# `/bitstreams/<uuid>/download` do DSpace 7 sem renderização no servidor devolve a
# casca HTML do Angular, não o arquivo (achado real na coleta até 20 mil:
# repositorio.bc.ufg.br, 24 de 24 `conteudo_nao_e_pdf`). O arquivo está na API.
_BITSTREAM_DSPACE7 = re.compile(r"/bitstreams/([0-9a-f-]{36})/download", re.I)


def _endereco_interno(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if not host or host in _HOSTS_INTERNOS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


@dataclass
class ResultadoDownload:
    ok: bool
    caminho: Path | None = None
    url_pdf: str | None = None
    sha256: str | None = None
    bytes: int = 0
    motivo: str = ""


class ResolvedorTextoCompleto:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.timeout = cfg.get_path("coleta.http.timeout_s", 60)
        self.max_bytes = int(cfg.get_path("coleta.http.tamanho_max_pdf_mb", 120)) * 1024 * 1024
        self.respeitar_robots = cfg.get_path("coleta.http.respeitar_robots", True)
        self.limiter = RateLimiter(cfg.get_path("coleta.http.rps_repositorios", 0.33))
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.vetados: dict[str, str] = {}  # netloc -> motivo (robots.classificar)
        self._apis_dspace7: dict[str, list[str]] = {}  # origem+prefixo -> bases da API
        self._pagina_do_arquivo: dict[str, str] = {}  # url do arquivo -> página do item
        self.sessao = requests.Session()
        self.sessao.headers.update(
            {
                "User-Agent": cfg.user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
        )

    # ----------------------------------------------------------- robots.txt
    def _permitido(self, url: str) -> bool:
        if not self.respeitar_robots:
            return True
        partes = urllib.parse.urlsplit(url)
        dominio = f"{partes.scheme}://{partes.netloc}"
        if partes.netloc in self.vetados:
            return False
        if dominio not in self._robots:
            self._robots[dominio] = self._carregar_robots(dominio, partes.netloc)
        if partes.netloc in self.vetados:
            return False
        rp = self._robots[dominio]
        if rp is None:
            return True
        return rp.can_fetch(self.cfg.user_agent(), url)

    def _carregar_robots(self, dominio: str, netloc: str) -> urllib.robotparser.RobotFileParser | None:
        """
        Baixa o robots.txt pela mesma sessão (nosso User-Agent, ritmo do domínio)
        e o classifica pela letra e pelo espírito (`robots.classificar`). É o que
        protege o domínio FINAL de um link hdl.handle.net, que não tem evidência
        prévia: veto a robôs de IA ou desafio anti-robô tiram o domínio da coleta.
        """
        url = f"{dominio}/robots.txt"
        try:
            self.limiter.aguardar(netloc)
            resp = self.sessao.get(url, timeout=self.timeout, allow_redirects=False)
            for _ in range(5):  # robots.txt pode redirecionar (http -> https)
                destino = resp.headers.get("Location") if resp.status_code in (301, 302, 303, 307, 308) else None
                if not destino:
                    break
                url = urllib.parse.urljoin(url, destino)
                self.limiter.aguardar(urllib.parse.urlsplit(url).netloc)
                resp = self.sessao.get(url, timeout=self.timeout, allow_redirects=False)
            status, texto = resp.status_code, resp.text or ""
        except requests.RequestException as exc:
            # Inacessível: segue como antes; a página do item falha sozinha e o
            # disjuntor da instituição age.
            log.debug("robots.txt indisponível em %s (%s)", dominio, exc)
            return None

        veredito = robots_mod.classificar(status, texto, self.cfg.user_agent())
        if not veredito.permitido:
            self.vetados[netloc] = veredito.motivo
            log.warning("%s fora da coleta: robots.txt → %s", netloc, veredito.motivo)
            return None
        # Crawl-delay é uma instrução explícita do administrador. Respeitar 3s
        # quando o servidor pediu 15s é descumprir o robots.txt tanto quanto
        # ignorar um Disallow.
        if veredito.crawl_delay:
            self.limiter.definir_intervalo(netloc, veredito.crawl_delay)
            log.info("%s pede Crawl-delay de %ss — adotado", netloc, veredito.crawl_delay)
        if status != 200 or veredito.motivo == "robots_html_sem_regras":
            return None
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(texto.splitlines())
        return rp

    def _obter(self, url: str, stream: bool = False) -> requests.Response | None:
        # Redirecionamento seguido à mão: cada salto passa pelo robots.txt e pelo
        # ritmo DO SEU domínio. Com allow_redirects=True, um link hdl.handle.net
        # caía no repositório final sem checar o robots.txt dele e sem esperar a
        # vez daquele domínio.
        for _ in range(6):  # até 5 redirecionamentos
            if not self._permitido(url):
                log.info("bloqueado por robots.txt: %s", url)
                return None
            self.limiter.aguardar(urllib.parse.urlsplit(url).netloc)
            try:
                resp = self.sessao.get(url, timeout=self.timeout, stream=stream, allow_redirects=False)
            except requests.RequestException as exc:
                log.debug("falha ao acessar %s: %s", url, exc)
                return None
            destino = resp.headers.get("Location") if resp.status_code in (301, 302, 303, 307, 308) else None
            if not destino:
                return resp
            resp.close()
            url = urllib.parse.urljoin(url, destino)
        log.debug("redirecionamentos demais: %s", url)
        return None

    # ------------------------------------------------------ descobrir PDF
    def descobrir_url_pdf(self, url_registro: str) -> str | None:
        """Da página do trabalho no repositório até a URL do arquivo."""
        resp = self._obter(_sem_barra_dupla(url_registro))
        if resp is None or resp.status_code >= 400:
            return None

        tipo = (resp.headers.get("Content-Type") or "").lower()
        if "pdf" in tipo:
            return resp.url  # a própria URL já era o arquivo

        # Desafio anti-robô no lugar da página: o domínio sai da coleta na hora,
        # sem esperar o disjuntor (critério de parada do protocolo).
        if robots_mod.pagina_de_desafio(resp.text):
            netloc = urllib.parse.urlsplit(resp.url).netloc
            self.vetados[netloc] = "desafio_anti_robo"
            log.warning("%s fora da coleta: página de desafio anti-robô", netloc)
            return None

        sopa = BeautifulSoup(resp.text, "html.parser")

        # 1-2) metatags padronizadas
        for nome, attrs in META_PDF:
            tag = sopa.find(nome, attrs=attrs)
            if tag and tag.get("content"):
                return self._lembrar_pagina(
                    _no_mesmo_site(urllib.parse.urljoin(resp.url, tag["content"]), resp.url), resp.url)

        # 3) bitstreams do DSpace
        for a in sopa.find_all("a", href=True):
            href = a["href"]
            if re.search(r"/bitstreams?/", href) and ".pdf" in href.lower():
                return self._lembrar_pagina(urllib.parse.urljoin(resp.url, href), resp.url)

        # 4) qualquer .pdf na página
        candidatos = [
            urllib.parse.urljoin(resp.url, a["href"])
            for a in sopa.find_all("a", href=True)
            if a["href"].lower().split("?")[0].endswith(".pdf")
        ]
        if candidatos:
            return candidatos[0]

        # 5) DSpace 7 sem renderização no servidor: a página é só a "casca" do
        #    Angular (achado real: repositorio.ufrn.br, 1 KB, sem link nenhum).
        #    A API REST do próprio repositório lista os arquivos do item.
        url_pdf = self._descobrir_dspace7(resp.url)
        if url_pdf:
            return url_pdf

        # 6) último recurso: navegador de verdade
        if self.cfg.get_path("coleta.fallback_selenium", False):
            return self._descobrir_com_selenium(url_registro)

        return None

    def _json(self, url: str) -> dict | None:
        resp = self._obter(url) if url else None
        if resp is None or resp.status_code != 200 or "json" not in (resp.headers.get("Content-Type") or ""):
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _lembrar_pagina(self, url_pdf: str, url_pagina: str) -> str:
        self._pagina_do_arquivo[url_pdf] = url_pagina
        return url_pdf

    def _bases_api_dspace7(self, url: str) -> list[str]:
        """
        Base(s) da API REST de um DSpace 7. O padrão é `<origem>/server`, mas o site
        declara a verdadeira em `assets/config.json` (`rest.baseUrl`). Achados reais:
        patua.iec.gov.br → patuaback.iec.gov.br/server; repositorio.udesc.br →
        repositorio-api.udesc.br/server; repositorio.bc.ufg.br/tede → .../tedeserver
        (e a raiz do mesmo site → .../riserver). Endereço interno é descartado.
        """
        partes = urllib.parse.urlsplit(url)
        origem = f"{partes.scheme}://{partes.netloc}"
        m = re.match(r"^(/[^/]+)/(?:handle|items|entities|bitstreams)/", partes.path)
        prefixo = m.group(1) if m and m.group(1) not in ("/jspui", "/xmlui") else ""
        chave = origem + prefixo
        if chave not in self._apis_dspace7:
            bases = []
            for p in dict.fromkeys([prefixo, ""]):
                config = self._json(f"{origem}{p}/assets/config.json")
                base = str(((config or {}).get("rest") or {}).get("baseUrl") or "").rstrip("/")
                if base.startswith("http") and not _endereco_interno(base):
                    bases.append(base)
                    break
            bases.append(f"{origem}/server")
            self._apis_dspace7[chave] = list(dict.fromkeys(bases))
        return self._apis_dspace7[chave]

    def _descobrir_dspace7(self, url_pagina: str) -> str | None:
        """Item → pacote ORIGINAL → primeiro arquivo PDF, pela API REST do DSpace 7."""
        partes = urllib.parse.urlsplit(url_pagina)
        # Prefixo de handle nem sempre é numérico: `iec/5439`, `UDESC/20856`.
        handle = re.search(r"/handle/([\w.-]+/[\w.-]+)", partes.path)
        uuid = re.search(r"/items/([0-9a-f-]{36})", partes.path)
        if not (handle or uuid):
            return None
        for base in self._bases_api_dspace7(url_pagina):
            api = f"{base}/api"
            item = (self._json(f"{api}/pid/find?id=hdl:{handle.group(1)}") if handle
                    else self._json(f"{api}/core/items/{uuid.group(1)}"))
            if item:
                return self._pdf_do_item_dspace7(item)
        return None

    def _pdf_do_item_dspace7(self, item: dict) -> str | None:
        pacotes = self._json(item.get("_links", {}).get("bundles", {}).get("href", ""))
        for pacote in (pacotes or {}).get("_embedded", {}).get("bundles", []):
            if pacote.get("name") != "ORIGINAL":
                continue
            arquivos = self._json(pacote.get("_links", {}).get("bitstreams", {}).get("href", ""))
            for arquivo in (arquivos or {}).get("_embedded", {}).get("bitstreams", []):
                if (arquivo.get("name") or "").lower().endswith(".pdf"):
                    return arquivo.get("_links", {}).get("content", {}).get("href")
        return None

    def _descobrir_com_selenium(self, url: str) -> str | None:
        """
        Só vale a pena para repositórios que montam o link por JavaScript.
        É ~20x mais lento e consome muito mais memória — por isso fica
        desligado por padrão (ver comparação Requests+BS4 vs Selenium).
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
        except ImportError:
            log.warning("selenium não instalado; fallback ignorado")
            return None

        opcoes = Options()
        opcoes.add_argument("--headless=new")
        opcoes.add_argument("--no-sandbox")
        opcoes.add_argument("--disable-dev-shm-usage")
        opcoes.add_argument(f"--user-agent={self.cfg.user_agent()}")
        driver = None
        try:
            driver = webdriver.Chrome(options=opcoes)
            driver.set_page_load_timeout(self.timeout)
            driver.get(url)
            for elem in driver.find_elements(By.CSS_SELECTOR, "a[href$='.pdf'], a[href*='bitstream']"):
                href = elem.get_attribute("href")
                if href and ".pdf" in href.lower():
                    return href
        except Exception as exc:
            log.debug("selenium falhou em %s: %s", url, exc)
        finally:
            if driver:
                driver.quit()
        return None

    # ------------------------------------------------------------ download
    def baixar(self, url_pdf: str, destino: Path) -> ResultadoDownload:
        if destino.exists() and destino.stat().st_size > 0:
            return ResultadoDownload(
                ok=True, caminho=destino, url_pdf=url_pdf,
                sha256=sha256_arquivo(destino), bytes=destino.stat().st_size,
                motivo="ja_existia",
            )

        resp = self._obter(url_pdf, stream=True)
        if resp is None:
            return ResultadoDownload(False, motivo="bloqueado_ou_erro_rede")
        if resp.status_code >= 400:
            return ResultadoDownload(False, motivo=f"http_{resp.status_code}")

        declarado = int(resp.headers.get("Content-Length") or 0)
        if declarado and declarado > self.max_bytes:
            return ResultadoDownload(False, motivo="excede_tamanho_maximo")

        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_suffix(destino.suffix + ".part")
        escritos, primeiro = 0, b""
        try:
            with open(parcial, "wb") as fh:
                for pedaco in resp.iter_content(chunk_size=1 << 16):
                    if not pedaco:
                        continue
                    if not primeiro:
                        primeiro = pedaco[:8]
                    escritos += len(pedaco)
                    if escritos > self.max_bytes:
                        raise IOError("excede_tamanho_maximo")
                    fh.write(pedaco)
        except Exception as exc:
            parcial.unlink(missing_ok=True)
            return ResultadoDownload(False, motivo=f"erro_escrita:{exc}")

        if not primeiro.startswith(CABECALHOS_PDF):
            # Repositório devolveu página de login/erro com status 200.
            parcial.unlink(missing_ok=True)
            m = _BITSTREAM_DSPACE7.search(url_pdf or "")
            if m:
                pagina = self._pagina_do_arquivo.get(url_pdf, url_pdf)
                for base in self._bases_api_dspace7(pagina):
                    res = self.baixar(f"{base}/api/core/bitstreams/{m.group(1)}/content", destino)
                    if res.ok:
                        return res
            return ResultadoDownload(False, url_pdf=url_pdf, motivo="conteudo_nao_e_pdf")

        parcial.replace(destino)
        return ResultadoDownload(
            ok=True, caminho=destino, url_pdf=url_pdf,
            sha256=sha256_arquivo(destino), bytes=escritos,
        )

    # --------------------------------------------------------- alto nível
    def obter(self, urls_registro: list[str], destino: Path) -> ResultadoDownload:
        """Tenta cada URL do registro até conseguir um PDF válido."""
        ultimo = ResultadoDownload(False, motivo="sem_url")
        for url in urls_registro:
            if not url:
                continue
            url = _sem_barra_dupla(url)
            url_pdf = url if url.lower().split("?")[0].endswith(".pdf") else self.descobrir_url_pdf(url)
            if not url_pdf:
                ultimo = ResultadoDownload(False, motivo="pdf_nao_localizado")
                continue
            resultado = self.baixar(url_pdf, destino)
            if resultado.ok:
                return resultado
            ultimo = resultado
        return ultimo
