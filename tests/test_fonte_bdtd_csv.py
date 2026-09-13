"""Inventário da BDTD exportado pelo grupo, com os filtros de escopo deste projeto."""

import pandas as pd

from src.raw.fontes import ler_inventario_bdtd

LINHAS = [
    # id, título, instituição, direitos, url, assuntos, ano
    ("UFSC_1", "Atendimento odontológico a pacientes idosos", "UFSC", "openAccess",
     "https://repositorio.ufsc.br/handle/1/1", "Odontologia", 2019),
    ("UFSC_2", "Medição precisa de vazão em canais abertos", "UFSC", "openAccess",
     "https://repositorio.ufsc.br/handle/1/2", "Engenharia", 2018),
    ("UFSC_3", "Suplementação de novilhos em pastagem nativa", "UFSC", "openAccess",
     "https://repositorio.ufsc.br/handle/1/3", "Nutrição animal", 2017),
    ("UFSC_4", "Cuidado de enfermagem na atenção primária", "UFSC", "embargoedAccess",
     "https://repositorio.ufsc.br/handle/1/4", "Enfermagem", 2020),
    ("UFMG_1", "Epidemiologia da dengue", "UFMG", "openAccess",
     "https://repositorio.ufmg.br/handle/1/5", "", 2021),
    ("PUC_RS_1", "Uso de medicamentos por gestantes", "PUC_RS", "openAccess",
     "http://tede2.pucrs.br/tede2/handle/tede/1", "Farmácia", 2016),
    ("UFRN_1", "Pesquisa em gastronomia e hospitalidade", "UFRN", "openAccess",
     "https://repositorio.ufrn.br/handle/1/9", "Turismo", 2018),
]

CFG = {
    "somente_acesso_aberto": True,
    "excluir_instituicoes": ["UFMG"],
    "filtro_assunto": ["enfermag", "medicina", "medico", "medicas", "medicament", "medicacao",
                       "odontolog", "farmac", "nutric", "epidemiolog", "obstetr"],
    "excluir_assunto": [],
}
EXCLUIR_OAI = ["novilhos", "bovina"]


def escrever_csv(tmp_path):
    df = pd.DataFrame([{"id": i, "titulo": t, "autor": "Autora", "ano": float(a), "tipo": "dissertacao",
                        "instituicao": inst, "repositorio": "Repositório", "url": u, "direitos": d,
                        "idioma": "pt", "assuntos": s, "relevancia": "alta"}
                       for i, t, inst, d, u, s, a in LINHAS])
    caminho = tmp_path / "inventario_saude.csv.gz"
    df.to_csv(caminho, index=False, compression="gzip")
    return caminho


def test_filtros_do_projeto_sobre_o_inventario_do_grupo(tmp_path):
    ids = {r.chave_origem for r in ler_inventario_bdtd(escrever_csv(tmp_path), CFG, excluir_extra=EXCLUIR_OAI)}
    # entra "odontológico" (radical); saem medição, novilhos, embargo, UFMG e hospitalidade
    assert ids == {"UFSC_1", "PUC_RS_1"}


def test_piloto_limita_instituicoes_e_quantidade(tmp_path):
    cfg = {**CFG, "instituicoes": ["UFSC"], "limite_por_instituicao": 1}
    registros = ler_inventario_bdtd(escrever_csv(tmp_path), cfg, excluir_extra=EXCLUIR_OAI)
    assert [r.ies for r in registros] == ["UFSC"]


def test_registro_traz_link_direitos_e_ano_inteiro(tmp_path):
    registro = next(r for r in ler_inventario_bdtd(escrever_csv(tmp_path), CFG, excluir_extra=EXCLUIR_OAI)
                    if r.chave_origem == "PUC_RS_1")
    assert registro.url_landing == "http://tede2.pucrs.br/tede2/handle/tede/1"
    assert registro.extra["direitos"] == "openAccess"
    assert registro.ano == 2016 and registro.endpoint == ""
