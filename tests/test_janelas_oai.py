"""
Colheita OAI fatiada: janela que falha é dividida e tentada de novo; o que
não se recupera fica declarado. Servidor simulado, sem rede.
"""

import xml.etree.ElementTree as ET
from datetime import date, timedelta

from src.raw.fontes import NS, ClienteOAI


def _registro(ident: str) -> ET.Element:
    registro = ET.Element(f"{{{NS['oai']}}}record")
    cabecalho = ET.SubElement(registro, f"{{{NS['oai']}}}header")
    ET.SubElement(cabecalho, f"{{{NS['oai']}}}identifier").text = ident
    return registro


class ServidorFalso(ClienteOAI):
    """1 registro por dia; quebra em paginação profunda (`teto`) ou num dia ruim."""

    def __init__(self, dias: int, teto: int = 10_000, dias_quebrados=()):
        inicio = date(2026, 1, 1)
        self.por_dia = {inicio + timedelta(days=i): f"oai:x:{i + 1}" for i in range(dias)}
        self.teto = teto
        self.quebrados = {inicio + timedelta(days=d - 1) for d in dias_quebrados}

    def _listar_intervalo(self, metadata_prefix, conjunto, desde, ate):
        d0, d1 = date.fromisoformat(desde), date.fromisoformat(ate)
        emitidos = 0
        for dia in sorted(self.por_dia):
            if not d0 <= dia <= d1:
                continue
            if dia in self.quebrados:
                raise RuntimeError("HTTP 500 no resumptionToken")
            if emitidos == self.teto:
                raise RuntimeError("HTTP 500 em paginação profunda")
            emitidos += 1
            yield _registro(self.por_dia[dia])


class ServidorQuebrado(ServidorFalso):
    """Toda consulta falha: o caso real da UFMG em 2026-02-25..2026-06-25."""

    def __init__(self, dias):
        super().__init__(dias)
        self.consultas = 0

    def _listar_intervalo(self, metadata_prefix, conjunto, desde, ate):
        self.consultas += 1
        raise RuntimeError("500 Server Error")
        yield  # pragma: no cover


def test_falhas_seguidas_interrompem_a_colheita_e_declaram_o_intervalo_todo():
    servidor = ServidorQuebrado(dias=120)
    assert _colher(servidor, "2026-04-30") == []
    assert servidor.consultas == ServidorFalso.FALHAS_SEGUIDAS_MAX
    perdidas = servidor.janelas_perdidas
    assert min(p["de"] for p in perdidas) == "2026-01-01"
    assert max(p["ate"] for p in perdidas) == "2026-04-30"


def _colher(servidor: ServidorFalso, ate: str) -> list[str]:
    return [r.findtext("oai:header/oai:identifier", "", NS)
            for r in servidor.list_records("dim", "com_1", "2026-01-01", ate, janela_dias=120)]


def test_paginacao_profunda_se_recupera_dividindo_a_janela_sem_duplicar():
    servidor = ServidorFalso(dias=12, teto=5)
    colhidos = _colher(servidor, "2026-01-12")
    assert sorted(colhidos, key=lambda s: int(s.rsplit(":", 1)[1])) == [f"oai:x:{i}" for i in range(1, 13)]
    assert len(colhidos) == len(set(colhidos))
    assert getattr(servidor, "janelas_perdidas", []) == []


def test_dia_quebrado_fica_declarado_e_o_resto_e_recuperado():
    servidor = ServidorFalso(dias=12, dias_quebrados=[5])
    colhidos = set(_colher(servidor, "2026-01-12"))
    assert colhidos == {f"oai:x:{i}" for i in range(1, 13) if i != 5}
    perdidas = servidor.janelas_perdidas
    assert perdidas and all(p["de"] <= "2026-01-05" <= p["ate"] for p in perdidas)
    assert all((date.fromisoformat(p["ate"]) - date.fromisoformat(p["de"])).days <= 1 for p in perdidas)
