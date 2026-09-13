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
        "https://repo.exemplo.br/assets/config.json": _Resposta("https://repo.exemplo.br/assets/config.json", 404),
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


class _SessaoLivre(_SessaoFalsa):
    def get(self, url, **kwargs):
        self.pedidos.append(url)
        return self.respostas[url]


def test_dominio_final_que_veta_robos_de_ia_fica_fora_sem_pedir_a_pagina():
    # Caso PUC-RS, mas atrás de um hdl.handle.net: não há evidência prévia do
    # domínio final, então o veto tem de ser pego ao vivo.
    cfg = Config({"projeto": {"contato": "teste@ufpi.edu.br"}, "coleta": {"http": {}}})
    resolvedor = ResolvedorTextoCompleto(cfg)
    resolvedor.limiter = _LimiterEspiao()
    robots = "User-agent: *\nAllow: /\n\nUser-agent: ClaudeBot\nDisallow: /\n"
    resolvedor.sessao = _SessaoLivre({
        HANDLE: _Resposta(HANDLE, 302, FINAL),
        "https://repo.exemplo.br/robots.txt": _Resposta("https://repo.exemplo.br/robots.txt", texto=robots),
    })
    resolvedor._robots = {"https://hdl.handle.net": None}

    assert resolvedor.descobrir_url_pdf(HANDLE) is None
    assert FINAL not in resolvedor.sessao.pedidos
    assert resolvedor.vetados == {"repo.exemplo.br": "veto_robos_ia"}


def test_pagina_de_desafio_anti_robo_tira_o_dominio_na_primeira_vez():
    # Achado real: repositorio.fgv.br responde 200 com "Certificando de que você não é um bot!".
    pagina = "https://repo.exemplo.br/handle/10438/8662"
    html = "<html><head><title>Certificando de que você não é um bot!</title></head></html>"
    resolvedor = _resolvedor({pagina: _Resposta(pagina, texto=html)}, ["User-agent: *"])

    assert resolvedor.descobrir_url_pdf(pagina) is None
    assert resolvedor.vetados == {"repo.exemplo.br": "desafio_anti_robo"}
    assert resolvedor.descobrir_url_pdf("https://repo.exemplo.br/handle/1/2") is None
    assert resolvedor.sessao.pedidos == [pagina]  # o segundo item nem chega a ser pedido


def test_recaptcha_de_formulario_nao_e_desafio():
    from src.raw.robots import pagina_de_desafio

    assert not pagina_de_desafio('<form><div class="g-recaptcha" data-sitekey="x"></div></form>')


def test_metatag_com_ip_e_porta_do_angular_vira_o_site_publico():
    # Achado real: repositorio.uepb.edu.br publica http://200.129.73.159:4000/bitstreams/<uuid>/download.
    pagina = "https://repo.exemplo.br/items/b3506394-ccc9-4b3f-a06c-20bd213e2bcf"
    html = '<meta name="citation_pdf_url" content="http://200.129.73.159:4000/bitstreams/abc/download">'
    resolvedor = _resolvedor({pagina: _Resposta(pagina, texto=html)}, ["User-agent: *"])
    assert resolvedor.descobrir_url_pdf(pagina) == "https://repo.exemplo.br/bitstreams/abc/download"


def test_metatag_em_outro_dominio_de_verdade_e_mantida():
    from src.raw.fulltext import _no_mesmo_site

    assert _no_mesmo_site("https://arquivos.exemplo.br/tese.pdf", "https://repo.exemplo.br/handle/1/2") \
        == "https://arquivos.exemplo.br/tese.pdf"


def test_barra_dupla_no_caminho_do_link_e_corrigida():
    # Achado real: https://www.bdtd.ueg.br//handle/tede/89 dá 404.
    pagina = "https://repo.exemplo.br/handle/tede/89"
    resolvedor = _resolvedor({pagina: _Resposta(pagina, texto=HTML)}, ["User-agent: *"])
    assert resolvedor.descobrir_url_pdf("https://repo.exemplo.br//handle/tede/89") \
        == "https://repo.exemplo.br/bitstream/123/456/tese.pdf"
    assert resolvedor.sessao.pedidos == [pagina]


class _RespostaBinaria(_Resposta):
    def __init__(self, url, corpo, tipo):
        super().__init__(url)
        self.headers = {"Content-Type": tipo}
        self._corpo = corpo

    def iter_content(self, chunk_size=1):
        yield self._corpo


def test_download_dspace7_que_devolve_html_tenta_o_arquivo_pela_api(tmp_path):
    # Achado real (UFG): /bitstreams/<uuid>/download devolvia a casca do Angular.
    uuid = "84b3f2fc-5775-474f-9c19-f7c287f46944"
    download = f"https://repo.exemplo.br/bitstreams/{uuid}/download"
    conteudo = f"https://repo.exemplo.br/server/api/core/bitstreams/{uuid}/content"
    config = "https://repo.exemplo.br/assets/config.json"
    resolvedor = _resolvedor({download: _RespostaBinaria(download, b"<!DOCTYPE html><html>", "text/html"),
                              config: _Resposta(config, 404),
                              conteudo: _RespostaBinaria(conteudo, b"%PDF-1.7 corpo", "application/pdf")},
                             ["User-agent: *", "Disallow: /admin/"])

    res = resolvedor.baixar(download, tmp_path / "tese.pdf")

    assert res.ok and res.url_pdf == conteudo
    assert resolvedor.sessao.pedidos == [download, config, conteudo]
    assert (tmp_path / "tese.pdf").read_bytes().startswith(b"%PDF")


def test_dspace7_com_api_em_outro_endereco_declarado_no_config_json():
    # Achados reais: patua.iec.gov.br → patuaback.iec.gov.br/server;
    # repositorio.udesc.br → repositorio-api.udesc.br/server. Handle não numérico.
    pagina = "https://repo.exemplo.br/handle/iec/5439"
    api = "https://api.exemplo.br/server/api"
    conteudo = f"{api}/core/bitstreams/b1/content"
    config = "https://repo.exemplo.br/assets/config.json"
    respostas = {
        pagina: _Resposta(pagina, texto='<html><base href="/"><title>Patuá</title></html>'),
        config: _RespostaJson(config, {"rest": {"baseUrl": "https://api.exemplo.br/server",
                                                "ssrBaseUrl": "http://10.0.0.5:8080/server"}}),
        "https://api.exemplo.br/robots.txt": _Resposta("https://api.exemplo.br/robots.txt", 404),
        f"{api}/pid/find?id=hdl:iec/5439": _RespostaJson(
            f"{api}/pid/find", {"_links": {"bundles": {"href": f"{api}/core/items/i1/bundles"}}}),
        f"{api}/core/items/i1/bundles": _RespostaJson(f"{api}/core/items/i1/bundles", {"_embedded": {"bundles": [
            {"name": "ORIGINAL", "_links": {"bitstreams": {"href": f"{api}/core/bundles/o/bitstreams"}}}]}}),
        f"{api}/core/bundles/o/bitstreams": _RespostaJson(f"{api}/core/bundles/o/bitstreams", {"_embedded": {
            "bitstreams": [{"name": "tese.pdf", "_links": {"content": {"href": conteudo}}}]}}),
    }
    resolvedor = _resolvedor(respostas, ["User-agent: *"])
    assert resolvedor.descobrir_url_pdf(pagina) == conteudo


def test_download_dspace7_usa_a_api_do_prefixo_da_pagina(tmp_path):
    # Achado real: repositorio.bc.ufg.br/tede declara a API em /tedeserver (a raiz,
    # em /riserver), e a metatag do arquivo perde o prefixo /tede.
    uuid = "84b3f2fc-5775-474f-9c19-f7c287f46944"
    pagina = "https://repo.exemplo.br/tede/items/4df78089-f5d4-41f3-952d-d936ea88c673"
    download = f"https://repo.exemplo.br/bitstreams/{uuid}/download"
    config = "https://repo.exemplo.br/tede/assets/config.json"
    conteudo = f"https://repo.exemplo.br/tedeserver/api/core/bitstreams/{uuid}/content"
    resolvedor = _resolvedor({
        pagina: _Resposta(pagina, texto=f'<meta name="citation_pdf_url" content="{download}">'),
        download: _RespostaBinaria(download, b"<!DOCTYPE html><html>", "text/html"),
        config: _RespostaJson(config, {"rest": {"baseUrl": "https://repo.exemplo.br/tedeserver"}}),
        conteudo: _RespostaBinaria(conteudo, b"%PDF-1.7 corpo", "application/pdf"),
    }, ["User-agent: *"])

    res = resolvedor.baixar(resolvedor.descobrir_url_pdf(pagina), tmp_path / "tese.pdf")

    assert res.ok and res.url_pdf == conteudo


def test_robots_do_dominio_final_bloqueia_mesmo_vindo_de_redirecionamento():
    resolvedor = _resolvedor({HANDLE: _Resposta(HANDLE, 302, FINAL), FINAL: _Resposta(FINAL, texto=HTML)},
                             ["User-agent: *", "Disallow: /handle/"])
    assert resolvedor.descobrir_url_pdf(HANDLE) is None
    assert resolvedor.sessao.pedidos == [HANDLE]
