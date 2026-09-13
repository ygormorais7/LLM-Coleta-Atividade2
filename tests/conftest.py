"""
Fixtures compartilhadas. Nenhum teste escreve em data/: toda camada aponta
para um diretório temporário.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.common import Config  # noqa: E402

_CONECTORES = ["Além disso,", "Por outro lado,", "Nesse contexto,", "De modo geral,", "Em seguida,",
               "Assim,", "Contudo,", "Portanto,", "Ainda assim,", "Da mesma forma,"]
_SUJEITOS = ["o paciente", "a equipe de enfermagem", "o grupo controle", "a gestante", "o idoso internado",
             "a unidade básica", "o serviço de urgência", "a criança acompanhada", "o profissional de saúde",
             "a família do participante"]
_VERBOS = ["apresentou melhora", "relatou dificuldade", "recebeu orientação", "demonstrou adesão",
           "manteve acompanhamento", "precisou de encaminhamento", "teve avaliação", "passou por triagem",
           "recebeu tratamento", "mostrou evolução"]
_COMPLEMENTOS = ["durante o período de internação", "após a consulta inicial", "ao longo do seguimento",
                 "na atenção primária", "segundo os registros do prontuário", "conforme o protocolo clínico",
                 "em relação ao grupo comparado", "de acordo com a escala aplicada", "no domicílio",
                 "na unidade de terapia intensiva"]
_FINAIS = ["o que reforça a importância do cuidado integral.", "e isso foi discutido com a equipe.",
           "sem intercorrências graves.", "com resultados compatíveis com a literatura.",
           "o que exige novos estudos.", "e os dados foram registrados em planilha.",
           "como descrito na metodologia.", "com apoio da coordenação do serviço.",
           "e a análise estatística confirmou a diferença.", "o que foi observado em outras regiões."]


def _texto_portugues(semente: int, paragrafos: int = 12, frases: int = 6) -> str:
    rnd = random.Random(semente)
    blocos = []
    for _ in range(paragrafos):
        blocos.append(" ".join(
            f"{rnd.choice(_CONECTORES)} {rnd.choice(_SUJEITOS)} {rnd.choice(_VERBOS)} "
            f"{rnd.choice(_COMPLEMENTOS)}, {rnd.choice(_FINAIS)}"
            for _ in range(frases)
        ))
    return "RESUMO\n\n" + "\n\n".join(blocos)


@pytest.fixture
def gerar_texto():
    """Texto em português que passa nos filtros de qualidade da Processed."""
    return _texto_portugues


@pytest.fixture
def cfg_tmp(tmp_path):
    """Config real do projeto, com todas as camadas num diretório temporário."""
    cfg = Config.carregar()
    cfg["caminhos"] = {c: str(tmp_path / c) for c in ("raw", "staging", "processed", "curated")}
    cfg["caminhos"]["relatorios"] = str(tmp_path / "reports")
    # Os textos sintéticos compartilham vocabulário; a dedup aproximada não é
    # o que estes testes medem.
    cfg["processed"]["deduplicacao"]["fuzzy"] = False
    cfg["processed"]["extracao"]["workers"] = 1
    return cfg
