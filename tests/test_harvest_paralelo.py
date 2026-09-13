"""Download por cota com estratos em paralelo e meta de PDFs. Resolvedor simulado, sem rede."""

import threading

from src.common import Relatorio, ler_jsonl
from src.raw import harvest
from src.raw.fulltext import ResultadoDownload


class _ResolvedorFalso:
    ativos = 0
    pico = 0
    trava = threading.Lock()

    def __init__(self, cfg):
        pass

    def obter(self, urls, destino):
        import time
        with _ResolvedorFalso.trava:
            _ResolvedorFalso.ativos += 1
            _ResolvedorFalso.pico = max(_ResolvedorFalso.pico, _ResolvedorFalso.ativos)
        time.sleep(0.02)
        destino.write_bytes(b"%PDF-1.4 falso")
        with _ResolvedorFalso.trava:
            _ResolvedorFalso.ativos -= 1
        return ResultadoDownload(ok=True, caminho=destino, url_pdf=urls[0], sha256="0" * 64, bytes=14)


def _candidatos(n_por_estrato, estratos):
    return [{"chave_origem": f"{e}:{i}", "estrato": e, "cota_estrato": 1000, "ordem_na_fila": i,
             "url_binario": f"https://{e}.exemplo.br/{i}.pdf", "extra": {"direitos": "Acesso Aberto"}}
            for e in estratos for i in range(n_por_estrato)]


def test_todos_os_estratos_sao_baixados_em_paralelo_sem_perder_item(cfg_tmp, monkeypatch):
    monkeypatch.setattr(harvest, "ResolvedorTextoCompleto", _ResolvedorFalso)
    _ResolvedorFalso.pico = 0
    rel = Relatorio(camada="raw", area="teste")

    harvest.baixar_por_cota(cfg_tmp, _candidatos(10, ["ufsc", "pucrs", "ufpr"]), rel)

    manifesto = list(ler_jsonl(cfg_tmp.dir_camada("raw") / "manifesto.jsonl"))
    assert len(manifesto) == 30 and all(m["baixado"] for m in manifesto)
    assert rel.saidas["pdfs_baixados"] == 30
    assert _ResolvedorFalso.pico > 4  # mais de um estrato ao mesmo tempo


def test_meta_de_pdfs_interrompe_a_coleta(cfg_tmp, monkeypatch):
    monkeypatch.setattr(harvest, "ResolvedorTextoCompleto", _ResolvedorFalso)
    cfg_tmp["coleta"]["meta_pdfs"] = 3
    rel = Relatorio(camada="raw", area="teste")

    harvest.baixar_por_cota(cfg_tmp, _candidatos(40, ["ufsc"]), rel)

    assert rel.metricas["meta_atingida"] is True
    assert 3 <= rel.saidas["pdfs_baixados"] <= 8  # para no fim do bloco em andamento
