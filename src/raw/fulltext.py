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

import re
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ..common import Config, RateLimiter, configurar_log, sha256_arquivo

log = configurar_log("raw.fulltext")

CABECALHOS_PDF = (b"%PDF",)
META_PDF = [
    ("meta", {"name": "citation_pdf_url"}),
    ("meta", {"name": "citation_fulltext_html_url"}),
    ("meta", {"name": "eprints.document_url"}),
    ("meta", {"property": "citation_pdf_url"}),
]


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
        if dominio not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{dominio}/robots.txt")
            try:
                self.limiter.aguardar(partes.netloc)
                rp.read()
            except Exception as exc:  # robots inacessível: assume permitido
                log.debug("robots.txt indisponível em %s (%s)", dominio, exc)
                rp = None
            self._robots[dominio] = rp

            # Crawl-delay é uma instrução explícita do administrador. Respeitar
            # 3s quando o servidor pediu 15s é descumprir o robots.txt tanto
            # quanto ignorar um Disallow.
            if rp is not None:
                try:
                    atraso = rp.crawl_delay(self.cfg.user_agent()) or rp.crawl_delay("*")
                except Exception:
                    atraso = None
                if atraso:
                    self.limiter.definir_intervalo(partes.netloc, float(atraso))
                    log.info("%s pede Crawl-delay de %ss — adotado",
                             partes.netloc, atraso)
        rp = self._robots[dominio]
        if rp is None:
            return True
        return rp.can_fetch(self.cfg.user_agent(), url)

    def _obter(self, url: str, stream: bool = False) -> requests.Response | None:
        if not self._permitido(url):
            log.info("bloqueado por robots.txt: %s", url)
            return None
        dominio = urllib.parse.urlsplit(url).netloc
        self.limiter.aguardar(dominio)
        try:
            return self.sessao.get(url, timeout=self.timeout, stream=stream, allow_redirects=True)
        except requests.RequestException as exc:
            log.debug("falha ao acessar %s: %s", url, exc)
            return None

    # ------------------------------------------------------ descobrir PDF
    def descobrir_url_pdf(self, url_registro: str) -> str | None:
        """Da página do trabalho no repositório até a URL do arquivo."""
        resp = self._obter(url_registro)
        if resp is None or resp.status_code >= 400:
            return None

        tipo = (resp.headers.get("Content-Type") or "").lower()
        if "pdf" in tipo:
            return resp.url  # a própria URL já era o arquivo

        sopa = BeautifulSoup(resp.text, "html.parser")

        # 1-2) metatags padronizadas
        for nome, attrs in META_PDF:
            tag = sopa.find(nome, attrs=attrs)
            if tag and tag.get("content"):
                return urllib.parse.urljoin(resp.url, tag["content"])

        # 3) bitstreams do DSpace
        for a in sopa.find_all("a", href=True):
            href = a["href"]
            if re.search(r"/bitstreams?/", href) and ".pdf" in href.lower():
                return urllib.parse.urljoin(resp.url, href)

        # 4) qualquer .pdf na página
        candidatos = [
            urllib.parse.urljoin(resp.url, a["href"])
            for a in sopa.find_all("a", href=True)
            if a["href"].lower().split("?")[0].endswith(".pdf")
        ]
        if candidatos:
            return candidatos[0]

        # 5) último recurso: navegador de verdade
        if self.cfg.get_path("coleta.fallback_selenium", False):
            return self._descobrir_com_selenium(url_registro)

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
            url_pdf = url if url.lower().split("?")[0].endswith(".pdf") else self.descobrir_url_pdf(url)
            if not url_pdf:
                ultimo = ResultadoDownload(False, motivo="pdf_nao_localizado")
                continue
            resultado = self.baixar(url_pdf, destino)
            if resultado.ok:
                return resultado
            ultimo = resultado
        return ultimo
