"""O preflight bloqueia coleta de domínio do inventário BDTD sem evidência de robots.txt."""

import preflight
from test_fonte_bdtd_csv import CFG, escrever_csv


def test_dominio_sem_evidencia_de_robots_bloqueia(cfg_tmp, tmp_path):
    cfg_tmp["inventario"]["fontes"]["bdtd_csv"] = {**CFG, "habilitada": True,
                                                   "arquivo": str(escrever_csv(tmp_path))}
    preflight.BLOQUEIOS.clear()
    preflight.checar_evidencia_bdtd_csv(cfg_tmp)
    assert any("robots.txt" in b for b in preflight.BLOQUEIOS)

    for dominio in ("https_repositorio_ufsc_br", "http_tede2_pucrs_br"):
        (cfg_tmp.dir_relatorios() / f"evidencia_robots_{dominio}.json").write_text("{}", encoding="utf-8")
    preflight.BLOQUEIOS.clear()
    preflight.checar_evidencia_bdtd_csv(cfg_tmp)
    assert preflight.BLOQUEIOS == []


def _evidencias(cfg_tmp):
    import json

    for nome, dominio, conteudo in (
        ("https_repositorio_ufsc_br", "https://repositorio.ufsc.br", "User-agent: *\nDisallow: /search\n"),
        ("http_tede2_pucrs_br", "http://tede2.pucrs.br", "User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n"),
    ):
        (cfg_tmp.dir_relatorios() / f"evidencia_robots_{nome}.json").write_text(
            json.dumps({"dominio": dominio, "status_http": 200, "conteudo": conteudo}), encoding="utf-8")


def test_candidatos_de_dominio_que_veta_robos_de_ia_saem(cfg_tmp, tmp_path):
    from src.raw.inventario import candidatos_bdtd

    cfg_tmp["inventario"]["fontes"]["bdtd_csv"] = {**CFG, "habilitada": True,
                                                   "arquivo": str(escrever_csv(tmp_path))}
    _evidencias(cfg_tmp)
    todos = candidatos_bdtd(cfg_tmp)
    filtrados = candidatos_bdtd(cfg_tmp, aplicar_robots=True)
    assert any("pucrs" in c["url_landing"] for c in todos)
    assert filtrados and not any("pucrs" in c["url_landing"] for c in filtrados)


def test_inventario_com_dominio_vetado_bloqueia_a_coleta(cfg_tmp, tmp_path):
    import json

    cfg_tmp["inventario"]["fontes"]["bdtd_csv"] = {**CFG, "habilitada": True,
                                                   "arquivo": str(escrever_csv(tmp_path))}
    _evidencias(cfg_tmp)
    inventario = cfg_tmp.dir_camada("raw") / "inventario.jsonl"
    inventario.parent.mkdir(parents=True, exist_ok=True)
    inventario.write_text(json.dumps({"fonte": "bdtd_inventario",
                                      "url_landing": "http://tede2.pucrs.br/tde_busca/1"}) + "\n", encoding="utf-8")
    preflight.BLOQUEIOS.clear()
    preflight.checar_evidencia_bdtd_csv(cfg_tmp)
    assert any("tede2.pucrs.br" in b for b in preflight.BLOQUEIOS)


def test_fonte_desabilitada_nao_exige_nada(cfg_tmp):
    cfg_tmp["inventario"]["fontes"]["bdtd_csv"] = {"habilitada": False}
    preflight.BLOQUEIOS.clear()
    preflight.checar_evidencia_bdtd_csv(cfg_tmp)
    assert preflight.BLOQUEIOS == []
