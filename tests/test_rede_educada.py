"""
Conduta de rede: ritmo por domínio em paralelo e robots.txt a cada salto de
redirecionamento. Sem rede: sessão e robots.txt simulados.
"""

import threading
import time
import urllib.robotparser

from src.common import Config, RateLimiter
from src.raw.fulltext import ResolvedorTextoCompleto


def test_dominios_diferentes_nao_esperam_um_pelo_outro():
    limiter = RateLimiter(req_por_segundo=2)  # 0,5 s por domínio
    limiter.aguardar("a")
    limiter.aguardar("b")
    inicio = time.monotonic()
    threads = [threading.Thread(target=limiter.aguardar, args=(d,)) for d in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.monotonic() - inicio < 0.8  # em série daria ~1,0 s


def test_mesmo_dominio_continua_respeitando_o_intervalo_com_threads():
    limiter = RateLimiter(req_por_segundo=5)  # 0,2 s
    marcas, trava = [], threading.Lock()

    def pedir():
        limiter.aguardar("repositorio")
        with trava:
            marcas.append(time.monotonic())

    threads = [threading.Thread(target=pedir) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert max(marcas) - min(marcas) >= 0.55  # 3 intervalos de 0,2 s


class _Resposta:
    def __init__(self, url, status=200, location=None, texto=""):
        self.url, self.status_code, self.text = url, status, texto
        self.headers = {"Location": location} if location else {"Content-Type": "text/html"}

    def close(self):
        pass


class _SessaoFalsa:
    def __init__(self, respostas):
        self.respostas, self.pedidos = respostas, []

    def get(self, url, **kwargs):
        assert kwargs.get("allow_redirects") is False
        self.pedidos.append(url)
        return self.respostas[url]


class _LimiterEspiao:
    def __init__(self):
        self.chaves = []

    def aguardar(self, chave):
        self.chaves.append(chave)


def _resolvedor(respostas, robots_repositorio):
    cfg = Config({"projeto": {"contato": "teste@ufpi.edu.br"}, "coleta": {"http": {}}})
    resolvedor = ResolvedorTextoCompleto(cfg)
    resolvedor.sessao = _SessaoFalsa(respostas)
    resolvedor.limiter = _LimiterEspiao()
    regras = urllib.robotparser.RobotFileParser()
    regras.parse(robots_repositorio)
    resolvedor._robots = {"https://hdl.handle.net": None, "https://repo.exemplo.br": regras}
    return resolvedor


HANDLE = "https://hdl.handle.net/123/456"
FINAL = "https://repo.exemplo.br/handle/123/456"
HTML = '<meta name="citation_pdf_url" content="/bitstream/123/456/tese.pdf">'


def test_redirecionamento_aplica_ritmo_e_robots_do_dominio_final():
    resolvedor = _resolvedor({HANDLE: _Resposta(HANDLE, 302, FINAL), FINAL: _Resposta(FINAL, texto=HTML)},
                             ["User-agent: *", "Disallow: /admin/"])
    assert resolvedor.descobrir_url_pdf(HANDLE) == "https://repo.exemplo.br/bitstream/123/456/tese.pdf"
    assert resolvedor.limiter.chaves == ["hdl.handle.net", "repo.exemplo.br"]


def test_metatag_com_localhost_vira_endereco_do_site_publico():
    # Achado real na Fiocruz: citation_pdf_url = http://localhost:4000/bitstreams/<uuid>/download
    pagina = "https://repo.exemplo.br/items/f207400b-3682-417a-be15-49e347d1deb2"
    html = '<meta name="citation_pdf_url" content="http://localhost:4000/bitstreams/abc/download">'
    resolvedor = _resolvedor({pagina: _Resposta(pagina, texto=html)}, ["User-agent: *", "Disallow: /admin/"])
    assert resolvedor.descobrir_url_pdf(pagina) == "https://repo.exemplo.br/bitstreams/abc/download"


class _RespostaJson(_Resposta):
    def __init__(self, url, dados):
        super().__init__(url)
        self.headers = {"Content-Type": "application/hal+json;charset=UTF-8"}
        self._dados = dados

    def json(self):
        return self._dados


def test_dspace7_sem_renderizacao_no_servidor_acha_o_pdf_pela_api():
    # Achado real na UFRN: a página do item é só a casca do Angular, sem link nenhum.
    api = "https://repo.exemplo.br/server/api"
    pagina = "https://repo.exemplo.br/handle/123456789/17814"
    conteudo = f"{api}/core/bitstreams/b1/content"
    respostas = {
        pagina: _Resposta(pagina, texto='<html><base href="/"><title>DSpace</title></html>'),
        f"{api}/pid/find?id=hdl:123456789/17814": _Resposta(f"{api}/pid/find", 302, f"{api}/core/items/i1"),
        f"{api}/core/items/i1": _RespostaJson(f"{api}/core/items/i1",
                                              {"_links": {"bundles": {"href": f"{api}/core/items/i1/bundles"}}}),
        f"{api}/core/items/i1/bundles": _RespostaJson(f"{api}/core/items/i1/bundles", {"_embedded": {"bundles": [
            {"name": "THUMBNAIL", "_links": {"bitstreams": {"href": f"{api}/core/bundles/t/bitstreams"}}},
            {"name": "ORIGINAL", "_links": {"bitstreams": {"href": f"{api}/core/bundles/o/bitstreams"}}},
        ]}}),
        f"{api}/core/bundles/o/bitstreams": _RespostaJson(f"{api}/core/bundles/o/bitstreams", {"_embedded": {
            "bitstreams": [{"name": "Dissertacao.PDF", "_links": {"content": {"href": conteudo}}}]}}),
    }
    resolvedor = _resolvedor(respostas, ["User-agent: *", "Disallow: /search"])
    assert resolvedor.descobrir_url_pdf(pagina) == conteudo
    assert f"{api}/core/bundles/t/bitstreams" not in resolvedor.sessao.pedidos  # miniatura não interessa


def test_pagina_sem_pdf_fora_do_dspace7_nao_consulta_api():
    pagina = "https://repo.exemplo.br/tede/detalhe.php?id=9"
    resolvedor = _resolvedor({pagina: _Resposta(pagina, texto="<html>nada</html>")}, ["User-agent: *"])
    assert resolvedor.descobrir_url_pdf(pagina) is None
    assert resolvedor.sessao.pedidos == [pagina]


def test_robots_do_dominio_final_bloqueia_mesmo_vindo_de_redirecionamento():
    resolvedor = _resolvedor({HANDLE: _Resposta(HANDLE, 302, FINAL), FINAL: _Resposta(FINAL, texto=HTML)},
                             ["User-agent: *", "Disallow: /handle/"])
    assert resolvedor.descobrir_url_pdf(HANDLE) is None
    assert resolvedor.sessao.pedidos == [HANDLE]
