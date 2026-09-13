"""
Regressões da anonimização. Os textos "intactos" são trechos reais do corpus
que eram mascarados por engano; os documentos "válidos" são gerados pelo
algoritmo oficial de cada documento — nunca números de pessoas reais.
"""

import pytest

from src.common import Config
from src.processed.clean import anonimizar

TODOS = ["cpf", "cnpj", "email", "telefone", "cep", "rg", "cartao_sus",
         "titulo_eleitor", "pis_pasep", "placa_veiculo", "url_perfil_social"]
CFG_TUDO = {"habilitada": True, "estrategia": "mascara", "detectores": {d: True for d in TODOS}}


def mascarar(texto: str, cfg=CFG_TUDO) -> str:
    return anonimizar(texto, cfg).texto


@pytest.fixture(scope="module")
def cfg_projeto():
    return Config.carregar().get_path("processed.anonimizacao")


# ---------------------------------------------------------------- geradores
def _pis(base10: str) -> str:
    soma = sum(int(d) * p for d, p in zip(base10, [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    dv = 11 - soma % 11
    return base10 + str(0 if dv >= 10 else dv)


def _titulo(seq8: str, uf: str) -> str:
    sp_ou_mg = uf in ("01", "02")

    def dv(soma):
        resto = soma % 11
        return 0 if resto == 10 else (1 if resto == 0 and sp_ou_mg else resto)

    d1 = dv(sum(int(seq8[i]) * (i + 2) for i in range(8)))
    d2 = dv(int(uf[0]) * 7 + int(uf[1]) * 8 + d1 * 9)
    return f"{seq8}{uf}{d1}{d2}"


def _cns_provisorio(base14: str) -> str:
    for troca in "0123456789":
        base = base14[:-1] + troca
        soma = sum(int(d) * (15 - i) for i, d in enumerate(base))
        d15 = (11 - soma % 11) % 11
        if d15 < 10:
            return base + str(d15)
    raise AssertionError("não gerou CNS")


def _trocar_ultimo(numero: str) -> str:
    return numero[:-1] + str((int(numero[-1]) + 1) % 10)


# ------------------------------------------------- já corrigidos na 3ª rodada
@pytest.mark.parametrize("texto", [
    "0101020058 aplicação de cariostático (por dente);",
    "Padrão de difração de raios X de PEG6000 (a), PVP (b)",
    "1991 1992 1993\nAnos",
])
def test_falsos_positivos_da_terceira_rodada_ficam_intactos(texto):
    assert mascarar(texto) == texto


# ------------------------------------------ diagnóstico de 2026-09-13 (Fase 2)
@pytest.mark.parametrize("texto", [
    "ORCID: https://orcid.org/0000-0002-8214-5734 Programa de Pós-Graduação",
    "Autora 0000-0001-6586-4561 escola de enfermagem",
    "DOI: 10.35699/2316-9389.2023.40258 UTILIZAÇÃO DE BANCO DE DADOS",
    "https://doi.org/10.1590/1413-81232018236.03942018. Disponível em:",
    "doi:10.1590/1809-98232016019.150085 39. Grover, S.",
    "hab) 310170605000006  568,7 310170605000003  642,8",
    "Coorte 2001  1.000 1.500 2.000 2.500 3.000 2001 2002 2003 2004",
    "Pandemia COVID-19 2020-2023 -0,51 0,59",
    "40.00  15.00\n\n2008-2009 7.47 1.64",
])
def test_identificadores_e_tabelas_do_corpus_ficam_intactos(texto):
    assert mascarar(texto) == texto


@pytest.mark.parametrize("texto", [
    "a enzima CYP2C19 (FLESCH, 2004)",
    "Em relação à classificação da OMS-2008, de 86 pacientes",
    "Análise do Global Burden of Disease 2017 (GBD-2017) mostrou",
])
def test_gene_e_sigla_de_estudo_intactos_com_config_do_projeto(texto, cfg_projeto):
    assert mascarar(texto, cfg_projeto) == texto


@pytest.mark.parametrize("telefone", [
    "(31) 3555-0100", "31 3555-0100", "(31)3555-0100", "+55-31-3555-0199", "(86) 99999-1234",
])
def test_telefone_real_e_mascarado(telefone):
    assert "[TELEFONE]" in mascarar(f"Contato do comitê: {telefone}.")


# ------------------------------- verificação do Curated na Fase 6 (2026-09-13)
@pytest.mark.parametrize("texto", [
    # Formatos reais achados no corpus; nomes e números trocados por fictícios.
    "Pesquisadora responsável. Telefone para Contato: (31)\n3555-0101\nSe você tiver perguntas",
    "Correspondência para a autora. Tel.: +55 31\n3555-0102.\nE-mail:",
    "Email: fulana@exemplo.com.br. Phone.: +55 31 3555\n0103; fax:",
    "Tel:\n(31)\n3555-0104.\nE-mail:",
])
def test_telefone_quebrado_em_linha_depois_do_ddd_e_mascarado(texto):
    assert "[TELEFONE]" in mascarar(texto)


@pytest.mark.parametrize("texto", [
    "5,55\n1999 9889 6596 66,70 530 5,36\n2000 5820 3913 67,23",
    "3,73-4,38 = -0,65\n2,45-2,83 = -0,38\n3797-3709 = 88\n101,47-101,27 = 0,20",
    "Pará de Minas\n3.694\n197.359\n\n58,07\n\nFormiga",
])
def test_tabela_com_quebra_de_linha_fica_intacta(texto):
    assert mascarar(texto) == texto


def test_pis_valido_mascarado_e_invalido_intacto():
    pis = _pis("1203456789")
    formatar = lambda p: f"{p[:3]}.{p[3:8]}.{p[8:10]}-{p[10]}"
    assert mascarar(f"PIS {formatar(pis)}") == "PIS [PIS_PASEP]"
    invalido = formatar(_trocar_ultimo(pis))
    assert mascarar(f"PIS {invalido}") == f"PIS {invalido}"


@pytest.mark.parametrize("uf", ["02", "13", "28"])
def test_titulo_de_eleitor_valido_mascarado_e_invalido_intacto(uf):
    titulo = _titulo("10234567", uf)
    formatar = lambda t: f"{t[:4]}.{t[4:8]}.{t[8:]}"
    assert mascarar(f"título {formatar(titulo)}") == "título [TITULO_ELEITOR]"
    invalido = formatar(_trocar_ultimo(titulo))
    assert mascarar(f"título {invalido}") == f"título {invalido}"


def test_cartao_sus_valido_mascarado_e_invalido_intacto():
    cns = _cns_provisorio("70000123456789")
    formatar = lambda c: f"{c[:3]} {c[3:7]} {c[7:11]} {c[11:]}"
    assert mascarar(f"CNS {formatar(cns)}") == "CNS [CARTAO_SUS]"
    invalido = formatar(_trocar_ultimo(cns))
    assert mascarar(f"CNS {invalido}") == f"CNS {invalido}"


# ------------------------------------------------------------------- gerais
@pytest.mark.parametrize("placa", ["ABC-1234", "ABC1D23"])
def test_placa_real_e_mascarada_quando_detector_ligado(placa):
    assert "[PLACA]" in mascarar(f"veículo de placa {placa} no local")


def test_cpf_so_e_mascarado_com_digito_verificador_valido():
    assert mascarar("CPF 529.982.247-25") == "CPF [CPF]"
    assert mascarar("processo 123.456.789-00") == "processo 123.456.789-00"


def test_email_e_mascarado_mesmo_perto_de_url():
    texto = "escreva para joao.silva@exemplo.com.br ou veja https://exemplo.br/contato"
    assert mascarar(texto) == "escreva para [EMAIL] ou veja https://exemplo.br/contato"


def test_perfil_de_rede_social_continua_mascarado():
    assert mascarar("perfil https://instagram.com/fulano.detal") == "perfil [URL_PERFIL]"


def test_detector_desligado_nao_atua():
    assert anonimizar("placa ABC-1234", {"habilitada": True, "detectores": {"email": True}}).texto \
        == "placa ABC-1234"


def test_rg_exige_numero_de_documento_e_nao_parametro_de_rmn():
    assert mascarar("Identidade RG: 12.345.678-9 do participante") == "Identidade [RG] do participante"
    texto = "AQ 2.6083827 sec RG 2050 DW 39.800 usec DE 7.50 usec"
    assert mascarar(texto) == texto


def test_achados_trazem_contexto_ja_mascarado():
    res = anonimizar("Fale com fulano@exemplo.com.br ou (31) 3555-0100 hoje.", CFG_TUDO)
    assert [a["tipo"] for a in res.achados] == ["EMAIL", "TELEFONE"]
    contextos = " ".join(a["contexto"] for a in res.achados)
    assert "fulano@" not in contextos and "3555" not in contextos
    assert "[EMAIL]" in contextos and "[TELEFONE]" in contextos


def test_estrategia_hash_nao_deixa_marcador_interno():
    res = anonimizar("CPF 529.982.247-25 e e-mail a@b.com.br", {**CFG_TUDO, "estrategia": "hash"})
    assert "\x01" not in res.texto and res.texto.startswith("CPF [CPF:")
