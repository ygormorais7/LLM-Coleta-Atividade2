"""Filtro de escopo: zootecnia sai, Saúde fica — com os casos reais do corpus."""

import pytest

from src.common import Config
from src.processed.run import _expressoes_permitidas_escopo, _termos_exclusao_escopo, fora_de_escopo
from src.raw.fontes import _normalizar_nome_coluna, bate_algum_termo


@pytest.fixture(scope="module")
def termos():
    return _termos_exclusao_escopo(Config.carregar())


@pytest.fixture(scope="module")
def permitidas():
    return _expressoes_permitidas_escopo(Config.carregar())


# Revisão à mão dos 42 excluídos como zootecnia (2026-09-13): estes eram Saúde.
@pytest.mark.parametrize("contexto", [
    "Análise dos resultados do protocolo de gesso seriado, órtese tornozelo-pé e exercícios domiciliares "
    "no tratamento do equino de crianças com paralisia cerebral",
    "correção cirúrgica do pé equino",
    "Influência de retentores intrarradiculares na resistência de cimento autoadesivo à dentina radicular bovina",
    "Efeito da idade nos aspectos morfológicos das dentinas radiculares humana e bovina",
    "meio mínimo essencial contendo 10% de soro fetal bovino inativado",
    "anticorpo conjugado à albumina sérica bovina (BSA) fixado em base sólida",
    "ensaios enzimáticos: calicreína tecidual do rato e tripsina bovina",
    "informações como condições de saneamento urbano e presença de mosquitos",
])
def test_saude_com_expressao_permitida_nao_e_excluida(contexto, termos, permitidas):
    assert not fora_de_escopo(contexto, termos, permitidas)


def test_expressao_permitida_nao_salva_zootecnia_de_verdade(termos, permitidas):
    assert fora_de_escopo("Novilhos Nelore: cultura celular com soro fetal bovino", termos, permitidas)


@pytest.mark.parametrize("titulo", [
    "Raiva bovina na área de impacto da hidrelétrica de Aimorés, Minas Gerais",
    "Suplementação de novilhos Nelore no período de transição águas-seca",
    "Situação epidemiológica da brucelose bovina e caracterização da pecuária",
    "Características físico-químicas e microbiológicas da silagem ácida de pescado",
    "Produção de milho adubado com biofertilizante suíno",
])
def test_zootecnia_e_excluida(titulo, termos):
    assert fora_de_escopo(titulo, termos)


@pytest.mark.parametrize("titulo", [
    "Efeito da epigalocatequina na pressão arterial de idosos",
    "Catequinas do chá verde e risco cardiovascular",
    "Cuidado de enfermagem à gestante na atenção primária",
])
def test_saude_nao_e_excluida(titulo, termos):
    assert not fora_de_escopo(titulo, termos)


def test_inclusao_aceita_radical():
    assert bate_algum_termo("Assistência obstétrica no SUS", [_normalizar_nome_coluna("obstetric")])


def test_exclusao_exige_palavra_inteira():
    assert not bate_algum_termo("catequina", ["equina"], palavra_inteira=True)
    assert bate_algum_termo("doença equina", ["equina"], palavra_inteira=True)


def test_sem_termos_nada_e_excluido():
    assert not fora_de_escopo("raiva bovina", [])
