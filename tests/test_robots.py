"""robots.txt pela letra e pelo espírito — com os dois casos reais do piloto."""

import pytest

from src.raw.robots import classificar, veta_robos_de_ia

UA = "bdtd-corpus/1.0 (pesquisa academica; UFPI; +mailto:teste@ufpi.edu.br) python-requests"
DSPACE = ("User-agent: *\nDisallow: /search\nDisallow: /admin/*\n\n"
          "# robôs de cópia em massa\nUser-agent: WebCopier\nDisallow: /\n")
PUCRS = ("User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n\n"
         "User-agent: ClaudeBot\nDisallow: /\n\nUser-agent: CCBot\nDisallow: /\n")
CLOUDFLARE = ("<!DOCTYPE html><html><head><title>Just a moment...</title>"
              "<script src='/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1'></script>")


@pytest.mark.parametrize("status,texto,permitido,motivo", [
    (200, DSPACE, True, "ok"),
    (200, PUCRS, False, "veto_robos_ia"),
    (200, CLOUDFLARE, False, "desafio_anti_robo"),
    (403, CLOUDFLARE, False, "desafio_anti_robo"),
    (404, "", True, "sem_robots"),
    (403, "Forbidden", False, "http_403"),
    (503, "", False, "http_503"),
    (None, "", False, "inacessivel"),
    (200, "User-agent: *\nDisallow: /\n", False, "bloqueia_nosso_agente"),
    (200, "<html><body>DSpace</body></html>", True, "robots_html_sem_regras"),
])
def test_classificacao_do_robots(status, texto, permitido, motivo):
    veredito = classificar(status, texto, UA)
    assert (veredito.permitido, veredito.motivo) == (permitido, motivo)


def test_link_para_localhost_ou_ip_privado_nao_e_candidato():
    from src.raw.fontes import host_interno

    assert host_interno("http://localhost:4000/handle/123/456")  # achado real no inventário
    assert host_interno("http://localhost:8080/jspui/handle/1/2")
    assert host_interno("http://192.168.0.10/handle/1/2") and host_interno("http://127.0.0.1/x")
    assert not host_interno("http://191.252.194.60:8080/handle/1/2")  # IP público de repositório
    assert not host_interno("https://repositorio.ufrn.br/handle/123/456")


def test_crawl_delay_vem_no_veredito():
    assert classificar(200, "User-agent: *\nCrawl-delay: 15\nDisallow: /search\n", UA).crawl_delay == 15.0


def test_veto_parcial_a_robo_de_ia_tambem_conta_e_disallow_vazio_nao():
    assert veta_robos_de_ia("User-agent: CCBot\nDisallow: /bitstream/\n")
    assert not veta_robos_de_ia("User-agent: GPTBot\nDisallow:\n")
    assert not veta_robos_de_ia(DSPACE)
