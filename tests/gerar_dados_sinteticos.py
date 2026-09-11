"""
Gera uma camada Raw FALSA para você desenvolver o pipeline sem bater na BDTD.

Rode isto antes de sair coletando de verdade. Um pipeline com bug que só é
descoberto depois de 6 horas de crawler é um pipeline caro — e cada rodada de
depuração significa milhares de requisições desnecessárias no servidor do IBICT.

    python tests/gerar_dados_sinteticos.py
    python run_pipeline.py --camadas staging processed curated

Os documentos 14 e 15 são quase-duplicatas do 0 (exata e aproximada), e o
documento 2 de cada trabalho carrega e-mail, CPF e telefone plantados —
serve para conferir se a dedup e a anonimização estão realmente funcionando.

Como os PDFs gerados são curtos, baixe temporariamente
`processed.qualidade.min_palavras` para ~120 durante o teste.
"""

from __future__ import annotations

import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # PyMuPDF

from src.common import Config, doc_id, escrever_jsonl

SUJEITOS = [
    "o modelo proposto", "a arquitetura avaliada", "o algoritmo de escalonamento",
    "a heurística gulosa", "o classificador treinado", "a base de dados construída",
    "o compilador experimental", "a rede convolucional", "o protocolo de consenso",
]
VERBOS = [
    "apresentou desempenho superior em", "reduziu de forma consistente",
    "demonstrou limitações quanto a", "obteve ganhos expressivos em",
    "manteve estabilidade sob", "exigiu ajustes finos em",
]
OBJETOS = [
    "cenários de alta concorrência", "conjuntos de dados desbalanceados",
    "ambientes com memória restrita", "cargas de trabalho heterogêneas",
    "instâncias de grande porte", "medições de latência de rede",
    "experimentos com validação cruzada", "análises de complexidade assintótica",
]
COMPLEMENTOS = [
    "conforme discutido no capítulo anterior.", "segundo a literatura consultada.",
    "de acordo com os testes estatísticos aplicados.",
    "ainda que com custo computacional elevado.",
    "o que confirma a hipótese inicial da pesquisa.",
    "embora novas evidências sejam necessárias.",
]
TEMAS = ["algoritmos", "redes neurais", "bancos de dados", "engenharia de software",
         "compiladores", "sistemas distribuídos", "aprendizado de máquina"]
INSTITUICOES = ["Universidade Federal do Piauí", "Universidade Federal do Ceará",
                "Universidade de São Paulo", "Universidade Federal de Pernambuco",
                "Universidade Estadual de Campinas"]


def paragrafo(rnd: random.Random, n: int = 6) -> str:
    return " ".join(
        f"{rnd.choice(SUJEITOS).capitalize()} {rnd.choice(VERBOS)} "
        f"{rnd.choice(OBJETOS)}, {rnd.choice(COMPLEMENTOS)}"
        for _ in range(n)
    )


def main(n_docs: int = 16) -> None:
    cfg = Config.carregar()
    for camada in ("raw", "staging", "processed", "curated"):
        shutil.rmtree(cfg.dir_camada(camada), ignore_errors=True)
    raw = cfg.dir_camada("raw")
    (raw / "pdf").mkdir(parents=True, exist_ok=True)

    registros, manifesto = [], []
    for i in range(n_docs):
        rnd = random.Random(i)
        ident = f"oai:bdtd-sintetico:{1000 + i}"
        did = doc_id(ident)
        tema = TEMAS[i % len(TEMAS)]

        paginas = ["RESUMO\n\n" + paragrafo(rnd, 8)] + [paragrafo(rnd, 9) for _ in range(5)]
        if i in (n_docs - 2, n_docs - 1):          # quase-duplicatas do doc 0
            r0 = random.Random(0)
            paginas = ["RESUMO\n\n" + paragrafo(r0, 8)] + [paragrafo(r0, 9) for _ in range(5)]
            if i == n_docs - 1:
                paginas.append("Parágrafo adicional exclusivo desta versão.")
        paginas[2] += (" O participante informou o e-mail joao.silva@exemplo.com.br, "
                       "o CPF 529.982.247-25 e o telefone (86) 99999-1234.")

        pdf = fitz.open()
        for n, conteudo in enumerate(paginas):
            pagina = pdf.new_page()
            pagina.insert_text((50, 35), "UNIVERSIDADE FEDERAL DO PIAUI - PPGCC", fontsize=7)
            pagina.insert_textbox(fitz.Rect(45, 55, 555, 760), conteudo, fontsize=9, align=3)
            pagina.insert_text((300, 800), str(n + 1), fontsize=8)
        caminho = raw / "pdf" / f"{did}.pdf"
        pdf.save(caminho)
        pdf.close()

        registros.append({
            "id": ident,
            "title": f"Um estudo experimental sobre {tema} em sistemas computacionais",
            "summary": [paragrafo(rnd, 5)],
            "authors": {"primary": {f"Sobrenome{i % 9}, Nome {i}": {"role": ["author"]}}},
            "formats": ["masterThesis" if i % 2 else "doctoralThesis"],
            "languages": ["por"],
            "publicationDates": [str(2014 + i % 9)],
            "subjects": [[tema], ["computação"], ["experimentação"]],
            "institutions": [INSTITUICOES[i % len(INSTITUICOES)]],
            "urls": [{"url": f"https://exemplo.invalido/handle/{i}"}],
            "rawData": {
                "eu_rights_str_mv": "info:eu-repo/semantics/openAccess",
                "dc.publisher.program.fl_str_mv": ["Programa de Pós-Graduação em Ciência da Computação"],
                "dc.contributor.advisor1.fl_str_mv": [f"Orientador{i % 4}, Fulano"],
            },
        })
        manifesto.append({
            "doc_id": did, "id_bdtd": ident,
            "urls_origem": [f"https://exemplo.invalido/handle/{i}"],
            "baixado": True, "arquivo": str(caminho),
            "url_pdf": f"https://exemplo.invalido/bitstream/{i}/t.pdf",
            "sha256": "0" * 64, "bytes": caminho.stat().st_size, "motivo": "",
        })

    escrever_jsonl(raw / "metadata" / "registros.jsonl", registros)
    escrever_jsonl(raw / "manifesto.jsonl", manifesto)
    print(f"camada Raw sintética criada em {raw} ({len(registros)} documentos)")


if __name__ == "__main__":
    main()
