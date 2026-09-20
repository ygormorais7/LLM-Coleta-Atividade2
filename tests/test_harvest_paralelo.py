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


class _ResolvedorQueFalhaNaUfpr(_ResolvedorFalso):
    chamadas: dict = {}

    def obter(self, urls, destino):
        inst = urls[0].split("//")[1].split(".")[0]
        with _ResolvedorFalso.trava:
            _ResolvedorQueFalhaNaUfpr.chamadas[inst] = _ResolvedorQueFalhaNaUfpr.chamadas.get(inst, 0) + 1
        if inst == "ufpr":
            return ResultadoDownload(False, motivo="pdf_nao_localizado")
        return super().obter(urls, destino)


def test_disjuntor_interrompe_so_a_instituicao_que_falha(cfg_tmp, monkeypatch):
    monkeypatch.setattr(harvest, "ResolvedorTextoCompleto", _ResolvedorQueFalhaNaUfpr)
    _ResolvedorQueFalhaNaUfpr.chamadas = {}
    cfg_tmp["coleta"]["disjuntor"] = {"min_tentativas": 10, "taxa_minima": 0.70}
    rel = Relatorio(camada="raw", area="teste")

    harvest.baixar_por_cota(cfg_tmp, _candidatos(60, ["ufpr", "ufrn"]), rel)

    assert list(rel.metricas["instituicoes_interrompidas"]) == ["ufpr"]
    assert _ResolvedorQueFalhaNaUfpr.chamadas["ufpr"] <= 10 + 8  # para no bloco em andamento
    assert _ResolvedorQueFalhaNaUfpr.chamadas["ufrn"] == 60
    # manifesto gravado item a item também tem as falhas
    manifesto = list(ler_jsonl(cfg_tmp.dir_camada("raw") / "manifesto.jsonl"))
    assert sum(1 for m in manifesto if not m["baixado"]) == _ResolvedorQueFalhaNaUfpr.chamadas["ufpr"]


def test_disjuntor_considera_o_historico_ao_retomar(cfg_tmp, monkeypatch):
    # Retomada: 30 PDFs já obtidos (manifesto + disco); os 20 restantes falham.
    # Sem histórico, cortaria na 10ª falha; com ele, só quando 30/(30+k) < 70%.
    from src.common import escrever_jsonl

    monkeypatch.setattr(harvest, "ResolvedorTextoCompleto", _ResolvedorQueFalhaNaUfpr)
    _ResolvedorQueFalhaNaUfpr.chamadas = {}
    cfg_tmp["coleta"]["disjuntor"] = {"min_tentativas": 10, "taxa_minima": 0.70}
    candidatos = _candidatos(50, ["ufpr"])
    dir_raw = cfg_tmp.dir_camada("raw")
    (dir_raw / "pdf").mkdir(parents=True, exist_ok=True)
    feitos = []
    for c in candidatos[:30]:
        did = harvest.doc_id(c["chave_origem"])
        arquivo = dir_raw / "pdf" / f"{did}.pdf"
        arquivo.write_bytes(b"%PDF-1.4 falso")
        feitos.append({"doc_id": did, "baixado": True, "arquivo": str(arquivo), "estrato": "ufpr"})
    escrever_jsonl(dir_raw / "manifesto.jsonl", feitos)
    rel = Relatorio(camada="raw", area="teste")

    harvest.baixar_por_cota(cfg_tmp, candidatos, rel)

    assert "ufpr" in rel.metricas["instituicoes_interrompidas"]
    assert 13 <= _ResolvedorQueFalhaNaUfpr.chamadas["ufpr"] <= 13 + 8


class _ResolvedorSemResposta(_ResolvedorFalso):
    chamadas = 0

    def obter(self, urls, destino):
        with _ResolvedorFalso.trava:
            _ResolvedorSemResposta.chamadas += 1
        return ResultadoDownload(False, motivo="sem_resposta")


def _com_historico(cfg_tmp, candidatos, n):
    from src.common import escrever_jsonl

    dir_raw = cfg_tmp.dir_camada("raw")
    (dir_raw / "pdf").mkdir(parents=True, exist_ok=True)
    feitos = []
    for c in candidatos[:n]:
        did = harvest.doc_id(c["chave_origem"])
        arquivo = dir_raw / "pdf" / f"{did}.pdf"
        arquivo.write_bytes(b"%PDF-1.4 falso")
        feitos.append({"doc_id": did, "baixado": True, "arquivo": str(arquivo), "estrato": "ufpr"})
    escrever_jsonl(dir_raw / "manifesto.jsonl", feitos)


def test_sequencia_de_pdfs_ausentes_nao_corta_instituicao_boa(cfg_tmp, monkeypatch):
    # Achados reais: 62 PDFs ausentes seguidos na UFSCar e 25 links 404 na UFMA,
    # com as duas funcionando. Falha de conteúdo conta só na taxa acumulada.
    monkeypatch.setattr(harvest, "ResolvedorTextoCompleto", _ResolvedorQueFalhaNaUfpr)
    _ResolvedorQueFalhaNaUfpr.chamadas = {}
    cfg_tmp["coleta"]["disjuntor"] = {"min_tentativas": 10, "taxa_minima": 0.70, "falhas_seguidas_max": 15}
    candidatos = _candidatos(300, ["ufpr"])
    _com_historico(cfg_tmp, candidatos, 200)
    rel = Relatorio(camada="raw", area="teste")

    harvest.baixar_por_cota(cfg_tmp, candidatos, rel)

    motivo = rel.metricas["instituicoes_interrompidas"]["ufpr"]
    assert "seguidas" not in motivo  # só a taxa acumulada cortou
    assert _ResolvedorQueFalhaNaUfpr.chamadas["ufpr"] > 15 + 8


def test_disjuntor_corta_servidor_que_para_de_responder_mesmo_com_historico_bom(cfg_tmp, monkeypatch):
    # Achado real (14/09/2026): a Fiocruz tinha 842 PDFs, parou de responder e,
    # pela taxa acumulada, só seria cortada depois de centenas de falhas seguidas.
    monkeypatch.setattr(harvest, "ResolvedorTextoCompleto", _ResolvedorSemResposta)
    _ResolvedorSemResposta.chamadas = 0
    cfg_tmp["coleta"]["disjuntor"] = {"min_tentativas": 10, "taxa_minima": 0.70, "falhas_seguidas_max": 15}
    candidatos = _candidatos(300, ["ufpr"])
    _com_historico(cfg_tmp, candidatos, 200)
    rel = Relatorio(camada="raw", area="teste")

    harvest.baixar_por_cota(cfg_tmp, candidatos, rel)

    assert "falhas de rede seguidas" in rel.metricas["instituicoes_interrompidas"]["ufpr"]
    assert _ResolvedorSemResposta.chamadas <= 15 + 8  # não as ~86 da taxa acumulada


def test_instituicao_suspensa_nao_recebe_nenhuma_requisicao(cfg_tmp, monkeypatch):
    monkeypatch.setattr(harvest, "ResolvedorTextoCompleto", _ResolvedorQueFalhaNaUfpr)
    _ResolvedorQueFalhaNaUfpr.chamadas = {}
    cfg_tmp["coleta"]["instituicoes_suspensas"] = {"UFPR": "servidor de handles fora do ar"}
    rel = Relatorio(camada="raw", area="teste")

    harvest.baixar_por_cota(cfg_tmp, _candidatos(30, ["ufpr", "ufrn"]), rel)

    assert "ufpr" not in _ResolvedorQueFalhaNaUfpr.chamadas
    assert _ResolvedorQueFalhaNaUfpr.chamadas["ufrn"] == 30
    assert rel.metricas["instituicoes_suspensas"] == {"ufpr": "servidor de handles fora do ar"}


def test_rodadas_espalham_a_meta_entre_instituicoes(cfg_tmp, monkeypatch):
    monkeypatch.setattr(harvest, "ResolvedorTextoCompleto", _ResolvedorFalso)
    cfg_tmp["coleta"].update({"meta_pdfs": 20, "rodada_por_instituicao": 8, "max_instituicoes_paralelas": 1})
    rel = Relatorio(camada="raw", area="teste")

    harvest.baixar_por_cota(cfg_tmp, _candidatos(50, ["a", "b"]), rel)

    manifesto = list(ler_jsonl(cfg_tmp.dir_camada("raw") / "manifesto.jsonl"))
    por_inst = {e: sum(1 for m in manifesto if m["estrato"] == e) for e in ("a", "b")}
    assert por_inst["a"] >= 8 and por_inst["b"] >= 8  # sem rodadas, "a" levaria os 20


def test_meta_de_pdfs_interrompe_a_coleta(cfg_tmp, monkeypatch):
    monkeypatch.setattr(harvest, "ResolvedorTextoCompleto", _ResolvedorFalso)
    cfg_tmp["coleta"]["meta_pdfs"] = 3
    rel = Relatorio(camada="raw", area="teste")

    harvest.baixar_por_cota(cfg_tmp, _candidatos(40, ["ufsc"]), rel)

    assert rel.metricas["meta_atingida"] is True
    assert 3 <= rel.saidas["pdfs_baixados"] <= 8  # para no fim do bloco em andamento
