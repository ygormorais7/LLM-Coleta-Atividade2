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


def test_fonte_desabilitada_nao_exige_nada(cfg_tmp):
    cfg_tmp["inventario"]["fontes"]["bdtd_csv"] = {"habilitada": False}
    preflight.BLOQUEIOS.clear()
    preflight.checar_evidencia_bdtd_csv(cfg_tmp)
    assert preflight.BLOQUEIOS == []
