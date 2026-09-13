"""
CAMADA CURATED — moldagem para consumo.

As camadas anteriores tratam do dado. Esta trata do CONSUMIDOR: o mesmo
corpus processado gera quatro produtos diferentes, porque quatro aplicações
diferentes precisam de formatos incompatíveis entre si.

  1. pretreino/   pré-treino continuado  -> documento inteiro, JSONL
  2. sft/         fine-tuning            -> pares instrução/resposta
  3. rag/         busca semântica        -> chunks com contexto desnormalizado
  4. benchmark/   avaliação              -> recuperação, múltipla escolha, perplexidade

Duas decisões que valem a pena defender na apresentação:

  - O split é feito POR GRUPO (autor + programa), não por documento. Se o
    mesmo orientando tem dissertação e tese, ou se o mesmo laboratório
    produz trabalhos com trechos de metodologia idênticos, dividir por
    documento vaza estilo e conteúdo entre treino e teste.

  - O conjunto de avaliação é DESCONTAMINADO contra o treino por MinHash
    depois do split. Qualquer documento de treino que se pareça demais com
    um de teste é removido do treino, não do teste.
"""

from __future__ import annotations

import json
import random
import re
from datetime import date
from pathlib import Path

import pandas as pd

from ..common import Config, Relatorio, configurar_log, escrever_jsonl
from ..processed import dedup as dedup_mod

log = configurar_log("curated.build")


# --------------------------------------------------------------------------
# Carga e split
# --------------------------------------------------------------------------
def carregar_corpus(cfg: Config) -> tuple[pd.DataFrame, dict[str, str]]:
    dir_stg = cfg.dir_camada("staging")
    dir_proc = cfg.dir_camada("processed")

    docs = pd.read_parquet(dir_stg / "documentos.parquet")
    metricas = pd.read_parquet(dir_proc / "documentos.parquet")
    autores = pd.read_parquet(dir_stg / "autores.parquet")
    assuntos = pd.read_parquet(dir_stg / "assuntos.parquet")

    # suffixes explícito: staging e processed têm colunas homônimas (idioma,
    # caracteres). Sem isso o pandas cria idioma_x/idioma_y e o código quebra
    # de um jeito silencioso e irritante.
    df = docs.merge(metricas, on="doc_id", how="inner", suffixes=("", "_proc"))
    if "no_corpus" in df.columns:
        df = df[df["no_corpus"]].copy()
    else:
        df = df.copy()

    # Título e resumo anonimizados, idioma/tipo/ano padronizados: tudo vem da
    # Processed, nunca cru da Staging.
    tratados = pd.read_parquet(dir_proc / "metadados.parquet").set_index("doc_id")
    for coluna in tratados.columns:
        valores = df["doc_id"].map(tratados[coluna])
        df[coluna] = valores if pd.api.types.is_numeric_dtype(tratados[coluna]) else valores.fillna("")

    if len(autores):
        principais = autores[autores["papel"] == "autor"].groupby("doc_id")["nome"].first()
        df["autor"] = df["doc_id"].map(principais).fillna("")
    else:
        df["autor"] = ""

    if len(assuntos):
        agrupados = assuntos.groupby("doc_id")["assunto"].apply(lambda s: "; ".join(s[:12]))
        df["palavras_chave"] = df["doc_id"].map(agrupados).fillna("")
    else:
        df["palavras_chave"] = ""

    textos = {}
    for did in df["doc_id"]:
        caminho = dir_proc / "texto" / f"{did}.txt"
        if caminho.exists():
            textos[did] = caminho.read_text(encoding="utf-8")
    df = df[df["doc_id"].isin(textos)].reset_index(drop=True)
    return df, textos


def dividir(df: pd.DataFrame, cfg: Config, textos: dict[str, str]) -> pd.DataFrame:
    cfg_s = cfg.get_path("curated.splits", {}) or {}
    random.seed(int(cfg_s.get("semente", 42)))

    if cfg_s.get("agrupar_por") == "autor_programa":
        chave = (df["autor"].fillna("") + "||" + df["programa"].fillna("")).str.lower()
        chave = chave.where(chave.str.strip() != "||", df["doc_id"])
    else:
        chave = df["doc_id"]
    df = df.assign(_grupo=chave)

    grupos = sorted(df["_grupo"].unique())
    random.shuffle(grupos)
    n = len(grupos)
    n_tr = int(n * float(cfg_s.get("treino", 0.90)))
    n_va = int(n * float(cfg_s.get("validacao", 0.05)))

    atribuicao = {}
    for i, g in enumerate(grupos):
        atribuicao[g] = "treino" if i < n_tr else ("validacao" if i < n_tr + n_va else "teste")
    df["split"] = df["_grupo"].map(atribuicao)

    # Descontaminação: remove do TREINO o que se parece com avaliação.
    treino = {d: textos[d] for d in df.loc[df["split"] == "treino", "doc_id"]}
    avaliacao = {d: textos[d] for d in df.loc[df["split"] != "treino", "doc_id"]}
    if treino and avaliacao:
        contaminados = dedup_mod.descontaminar(treino, avaliacao)
        df.loc[df["doc_id"].isin(contaminados), "split"] = "descartado_contaminado"

    return df.drop(columns=["_grupo"])


def _fonte(id_origem, url_registro) -> str:
    """De onde o documento veio de fato: OAI-PMH do repositório ou inventário da BDTD."""
    ident = str(id_origem or "")
    if ident.startswith("oai:") and ident.count(":") >= 2:
        return f"OAI-PMH {ident.split(':')[1]}"
    m = re.match(r"https?://([^/]+)", str(url_registro or ""))
    return f"inventário BDTD → {m.group(1)}" if m else "inventário BDTD"


def _meta(linha) -> dict:
    return {
        "doc_id": linha.doc_id,
        "titulo": linha.titulo,
        "autor": linha.autor,
        "instituicao": linha.instituicao,
        "programa": linha.programa,
        "ano": None if pd.isna(linha.ano) else int(linha.ano),
        "tipo": linha.tipo,
        "area": linha.area_projeto,
        "idioma": getattr(linha, "idioma", ""),
        "direitos": linha.direitos,
        "url": linha.url_registro,
        "fonte": _fonte(getattr(linha, "id_bdtd", ""), linha.url_registro),
    }


# --------------------------------------------------------------------------
# 1. Pré-treino continuado
# --------------------------------------------------------------------------
def gerar_pretreino(df: pd.DataFrame, textos: dict, dir_out: Path, cfg: Config) -> dict:
    cfg_p = cfg.get_path("curated.pretreino", {}) or {}
    por_shard = int(cfg_p.get("max_docs_por_shard", 5000))
    destino = dir_out / "pretreino"
    destino.mkdir(parents=True, exist_ok=True)

    resumo = {}
    for split in ("treino", "validacao", "teste"):
        sub = df[df["split"] == split]
        registros = []
        for linha in sub.itertuples():
            registros.append(
                {
                    "id": linha.doc_id,
                    "text": textos[linha.doc_id],   # nome de campo esperado por
                    "meta": _meta(linha),           # HF datasets / nanotron / litgpt
                }
            )
        for s in range(0, max(len(registros), 1), por_shard):
            fatia = registros[s:s + por_shard]
            if not fatia:
                break
            arq = destino / f"{split}-{s // por_shard:04d}.jsonl"
            escrever_jsonl(arq, fatia)
        resumo[split] = len(registros)

    log.info("pré-treino: %s", resumo)
    return resumo


# --------------------------------------------------------------------------
# 2. Fine-tuning (SFT)
# --------------------------------------------------------------------------
_TEMPLATES = [
    ("Explique, em um parágrafo, do que trata o trabalho intitulado \"{titulo}\".", "resumo"),
    ("Quais são as palavras-chave do trabalho \"{titulo}\"?", "palavras_chave"),
    ("Escreva o resumo de uma {tipo} de {programa} da {instituicao} sobre o seguinte tema: {palavras_chave}.", "resumo"),
    ("Com base no resumo a seguir, proponha um título acadêmico adequado.\n\nResumo: {resumo}", "titulo"),
    ("Leia a introdução da {tipo} a seguir, defendida na {instituicao}, e escreva o resumo do trabalho."
     "\n\n{trecho}", "sintese_trecho"),
]


_STOP_PT_SFT = {"de","da","do","das","dos","e","o","a","os","as","em","no","na",
                "para","por","com","que","um","uma","se","ao","como","foi","não"}


def _e_portugues(texto: str, minimo: float = 0.06) -> bool:
    """
    Guarda de idioma para o SFT.

    Sem isso o dataset gera pergunta em português com resposta em inglês,
    porque o resumo do repositório às vezes é o abstract. É um defeito que
    nenhum filtro de qualidade pega — o inglês está perfeitamente bem escrito.
    """
    palavras = re.findall(r"\w+", texto.lower())
    if len(palavras) < 20:
        return True
    # "a", "as", "do", "no" também são palavras inglesas: sem comparar com o
    # inglês, um abstract passava como português (achado real no SFT).
    pt = sum(1 for p in palavras if p in _STOP_PT_SFT) / len(palavras)
    en = sum(1 for p in palavras if p in _STOP_EN_SFT) / len(palavras)
    return pt >= minimo and pt > en


_STOP_EN_SFT = {"the", "of", "and", "in", "to", "is", "was", "with", "were", "for",
                "this", "that", "are", "by", "from", "which"}

# Título "INTRODUÇÃO" sozinho na linha (com ou sem número de capítulo).
_CABECALHO_INTRODUCAO = re.compile(
    r"(?im)^[ \t]*(?:\d+(?:\.\d+)*[ \t.–-]*)?INTRODU[ÇC][ÃA]O[ \t]*:?[ \t]*$")


def _primeiro_bloco(texto: str, palavras: int = 600) -> str:
    tokens = texto.split()
    return " ".join(tokens[:palavras])


def _limpar_palavras_chave(texto: str) -> str:
    """Tira código de classificação (`CNPQ::CIENCIAS DA SAUDE::...`) da lista."""
    itens = [i.strip() for i in re.split(r"[;|]", texto or "")]
    return "; ".join(i for i in itens if i and "::" not in i)


def _trecho_da_introducao(texto: str, resumo: str, palavras: int = 600) -> str:
    """
    Trecho para o par "leia a introdução e escreva o resumo".

    Duas tentativas anteriores deram errado, as duas achadas lendo pares:
    o começo do texto tratado É o resumo (a resposta vinha copiada na pergunta,
    186 de 243 pares), e o que vem logo depois do resumo é o ABSTRACT (a
    pergunta virava tradução, 109 de 178 pares). O trecho agora começa no
    título INTRODUÇÃO do corpo — o último que aparece nos primeiros 40% do
    texto, para pular a linha do sumário. Devolve "" (par descartado) se não
    houver título ou se o resumo aparecer no trecho.
    """
    alvo = " ".join(resumo.split())
    if len(alvo) < 120:
        return ""
    cabecalhos = [m for m in _CABECALHO_INTRODUCAO.finditer(texto) if m.start() < 0.4 * len(texto)]
    if not cabecalhos:
        return ""
    trecho = _primeiro_bloco(texto[cabecalhos[-1].end():], palavras)
    if alvo[:80] in trecho or alvo[-80:] in trecho:
        return ""
    return trecho


def gerar_sft(df: pd.DataFrame, textos: dict, dir_out: Path, cfg: Config) -> dict:
    """
    Pares instrução->resposta derivados de campos VERIFICÁVEIS do próprio
    documento (resumo, título, palavras-chave). Nenhuma resposta é inventada
    por um modelo — o que evita destilar alucinação para dentro do dataset.

    Se quiser instruções mais ricas depois, o caminho é gerar com um LLM
    e passar por revisão humana amostral, registrando isso no DATACARD.
    """
    cfg_f = cfg.get_path("curated.finetuning", {}) or {}
    min_car = int(cfg_f.get("min_caracteres_resposta", 200))
    max_por_doc = int(cfg_f.get("templates_por_doc", 4))
    destino = dir_out / "sft"
    destino.mkdir(parents=True, exist_ok=True)

    resumo = {}
    for split in ("treino", "validacao", "teste"):
        exemplos = []
        for linha in df[df["split"] == split].itertuples():
            campos = {
                "titulo": (linha.titulo or "").strip(),
                "resumo": (linha.resumo or "").strip(),
                "palavras_chave": _limpar_palavras_chave(linha.palavras_chave),
                "tipo": (linha.tipo or "tese").split("|")[0].strip() or "tese",
                "instituicao": (linha.instituicao or "").strip(),
                "programa": (linha.programa or "").split("|")[0].strip(),
            }
            campos["trecho"] = _trecho_da_introducao(textos[linha.doc_id], campos["resumo"])
            gerados = 0
            for pergunta, campo_resposta in _TEMPLATES:
                if gerados >= max_por_doc:
                    break
                if campo_resposta == "sintese_trecho":
                    resposta = campos["resumo"]  # resumo é a síntese de referência
                else:
                    resposta = campos.get(campo_resposta, "")
                if len(resposta) < min_car and campo_resposta != "titulo":
                    continue
                if campo_resposta != "titulo" and not _e_portugues(resposta):
                    continue
                # O texto que vai DENTRO da pergunta também precisa estar em
                # português: o resumo do repositório às vezes é o abstract.
                if any("{" + c + "}" in pergunta and not _e_portugues(campos[c])
                       for c in ("resumo", "trecho")):
                    continue
                if any(("{" + c + "}") in pergunta and not campos[c] for c in campos):
                    continue
                try:
                    instrucao = pergunta.format(**campos)
                except KeyError:
                    continue
                exemplos.append(
                    {
                        "id": f"{linha.doc_id}-{gerados}",
                        "messages": [
                            {"role": "user", "content": instrucao},
                            {"role": "assistant", "content": resposta},
                        ],
                        "meta": _meta(linha),
                    }
                )
                gerados += 1
        escrever_jsonl(destino / f"{split}.jsonl", exemplos)
        resumo[split] = len(exemplos)

    log.info("SFT: %s", resumo)
    return resumo


# --------------------------------------------------------------------------
# 3. RAG
# --------------------------------------------------------------------------
def _chunkar(texto: str, tamanho: int, sobreposicao: int):
    # Recorta o texto original (com as quebras de linha), em vez de juntar as
    # palavras com espaço: juntar linhas criava números que não existiam
    # ("1999\n9889 6596" virava telefone) e tirava a quebra de linha que a
    # anonimização usa para separar célula de tabela de telefone.
    posicoes = [m.span() for m in re.finditer(r"\S+", texto)]
    passo = max(tamanho - sobreposicao, 1)
    for inicio in range(0, len(posicoes), passo):
        pedaco = posicoes[inicio:inicio + tamanho]
        if len(pedaco) < 50:
            break
        yield texto[pedaco[0][0]:pedaco[-1][1]]


def gerar_rag(df: pd.DataFrame, textos: dict, dir_out: Path, cfg: Config) -> dict:
    """
    Chunks com metadados embutidos (desnormalização intencional): o resultado
    da busca vetorial precisa ser autocontido, sem JOIN com outra tabela para
    saber de que tese veio o trecho.

    Grava em LOTES direto no Parquet (`pyarrow.ParquetWriter`) em vez de
    acumular todos os ~150 mil chunks (~2.840 documentos inteiros
    reformatados com sobreposição) numa lista Python e só then montar um
    DataFrame gigante — foi isso que estourou memória e matou o processo
    duas vezes seguidas no meio deste passo, bem depois de pré-treino e SFT
    já terem passado sem problema.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    cfg_r = cfg.get_path("curated.rag", {}) or {}
    tamanho = int(cfg_r.get("tamanho_chunk_palavras", 500))
    sobrep = int(cfg_r.get("sobreposicao_palavras", 50))
    destino = dir_out / "rag"
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / "corpus_rag.parquet"

    TAMANHO_LOTE = 200  # documentos por lote; mantém o pico de memória baixo
    escritor: pq.ParquetWriter | None = None
    total_chunks = 0
    docs_vistos: set[str] = set()
    lote: list[dict] = []

    def _despejar(lote: list[dict]) -> None:
        nonlocal escritor, total_chunks
        if not lote:
            return
        if escritor is None:
            tabela = pa.Table.from_pylist(lote)
            escritor = pq.ParquetWriter(arq, tabela.schema)
        else:
            tabela = pa.Table.from_pylist(lote, schema=escritor.schema)
        escritor.write_table(tabela)
        total_chunks += len(lote)

    try:
        for n, linha in enumerate(df[df["split"] != "descartado_contaminado"].itertuples(), 1):
            meta = _meta(linha)
            for i, pedaco in enumerate(_chunkar(textos[linha.doc_id], tamanho, sobrep)):
                lote.append(
                    {
                        "chunk_id": f"{linha.doc_id}#{i:05d}",
                        "doc_id": linha.doc_id,
                        "indice_chunk": i,
                        "texto": pedaco,
                        "palavras": len(pedaco.split()),
                        "split": linha.split,
                        **{f"meta_{k}": v for k, v in meta.items() if k != "doc_id"},
                    }
                )
            docs_vistos.add(linha.doc_id)
            if n % TAMANHO_LOTE == 0:
                _despejar(lote)
                lote = []
        _despejar(lote)
    finally:
        if escritor is not None:
            escritor.close()

    log.info("RAG: %d chunks de %d documentos", total_chunks, len(docs_vistos))
    return {
        "chunks": total_chunks,
        "documentos": len(docs_vistos),
        "arquivo": str(arq),
    }


# --------------------------------------------------------------------------
# 4. Benchmarks
# --------------------------------------------------------------------------
def gerar_benchmarks(df: pd.DataFrame, textos: dict, dir_out: Path, cfg: Config) -> dict:
    cfg_b = cfg.get_path("curated.benchmark", {}) or {}
    destino = dir_out / "benchmark"
    destino.mkdir(parents=True, exist_ok=True)
    rng = random.Random(int(cfg.get_path("curated.splits.semente", 42)))

    avaliacao = df[df["split"].isin(["validacao", "teste"])]
    resumo = {}

    # ---- 4.1 Recuperação: resumo é a consulta, o documento é o gold.
    candidatos = avaliacao[avaliacao["resumo"].str.len() > 300]
    n = min(int(cfg_b.get("recuperacao_n", 300)), len(candidatos))
    itens = []
    for linha in candidatos.sample(n=n, random_state=42).itertuples() if n else []:
        itens.append(
            {
                "id": f"ret-{linha.doc_id}",
                "consulta": linha.resumo[:800],
                "doc_gold": linha.doc_id,
                "titulo_gold": linha.titulo,
                "metrica_sugerida": ["recall@5", "recall@10", "MRR"],
                "meta": _meta(linha),
            }
        )
    escrever_jsonl(destino / "recuperacao.jsonl", itens)
    resumo["recuperacao"] = len(itens)

    # ---- 4.2 Múltipla escolha a partir de metadados verificáveis.
    #      Sem LLM no meio: o gabarito vem do próprio registro bibliográfico,
    #      então não há alucinação possível no gabarito.
    # Distratores vêm do corpus inteiro, não só do split de avaliação: são
    # mais plausíveis assim, e num split pequeno o pool de avaliação sozinho
    # nem chega a ter 4 valores distintos.
    pool_inst = [i for i in df["instituicao"].dropna().unique() if i]
    pool_ano = [int(a) for a in df["ano"].dropna().unique()]
    itens = []
    alvo = int(cfg_b.get("multipla_escolha_n", 300))
    for linha in avaliacao.sample(frac=1.0, random_state=7).itertuples():
        if len(itens) >= alvo:
            break
        if not linha.resumo or len(linha.resumo) < 300:
            continue

        if linha.instituicao and len(pool_inst) >= 4:
            distratores = rng.sample([i for i in pool_inst if i != linha.instituicao], 3)
            alternativas = distratores + [linha.instituicao]
            rng.shuffle(alternativas)
            itens.append(
                {
                    "id": f"mc-inst-{linha.doc_id}",
                    "tipo": "instituicao_de_origem",
                    "pergunta": "Em qual instituição foi defendido o trabalho descrito no resumo a seguir?\n\n"
                                f"{linha.resumo[:900]}",
                    "alternativas": alternativas,
                    "resposta": linha.instituicao,
                    "meta": _meta(linha),
                }
            )

        if not pd.isna(linha.ano) and len(pool_ano) >= 4:
            ano = int(linha.ano)
            distratores = rng.sample([a for a in pool_ano if a != ano], 3)
            alternativas = [str(a) for a in distratores + [ano]]
            rng.shuffle(alternativas)
            itens.append(
                {
                    "id": f"mc-ano-{linha.doc_id}",
                    "tipo": "ano_de_defesa",
                    "pergunta": f"Em que ano foi defendido o trabalho \"{linha.titulo}\"?",
                    "alternativas": alternativas,
                    "resposta": str(ano),
                    "meta": _meta(linha),
                }
            )
    escrever_jsonl(destino / "multipla_escolha.jsonl", itens[:alvo])
    resumo["multipla_escolha"] = len(itens[:alvo])

    # ---- 4.3 Holdout de perplexidade (descontaminado por construção).
    n = min(int(cfg_b.get("perplexidade_n", 200)), len(avaliacao))
    itens = []
    for linha in avaliacao.sample(n=n, random_state=13).itertuples() if n else []:
        trecho = " ".join(textos[linha.doc_id].split()[:1024])
        itens.append({"id": f"ppl-{linha.doc_id}", "text": trecho, "meta": _meta(linha)})
    escrever_jsonl(destino / "perplexidade.jsonl", itens)
    resumo["perplexidade"] = len(itens)

    # ---- 4.4 README do benchmark, explicando como pontuar.
    (destino / "README.md").write_text(
        "# Benchmarks — como avaliar\n\n"
        "**recuperacao.jsonl** — indexe `rag/corpus_rag.parquet`, use `consulta` "
        "como query e verifique se algum chunk de `doc_gold` aparece no top-k. "
        "Reporte recall@5, recall@10 e MRR.\n\n"
        "**multipla_escolha.jsonl** — 4 alternativas, 1 correta. Gabarito vindo "
        "do registro bibliográfico, não de geração automática. Reporte acurácia "
        "e compare com o baseline aleatório de 25%.\n\n"
        "**perplexidade.jsonl** — holdout para medir perplexidade antes e depois "
        "do pré-treino continuado. Documentos deste conjunto foram removidos do "
        "treino por descontaminação MinHash.\n\n"
        "> Atenção: 4.1 e 4.2 avaliam recuperação e memória factual sobre o acervo, "
        "não conhecimento do domínio. Para avaliar domínio, é preciso um conjunto "
        "de perguntas escrito e revisado por humanos.\n",
        encoding="utf-8",
    )
    log.info("benchmarks: %s", resumo)
    return resumo


# --------------------------------------------------------------------------
# DATACARD
# --------------------------------------------------------------------------
def gerar_datacard(cfg: Config, df: pd.DataFrame, produtos: dict, dir_out: Path) -> Path:
    area = cfg.get_path("projeto.area_rotulo", "")
    por_split = df["split"].value_counts().to_dict()
    anos = df["ano"].dropna()
    instituicoes = df["instituicao"].value_counts().head(10)
    palavras = int(df["palavras"].sum()) if "palavras" in df else 0

    linhas_inst = "\n".join(f"| {i} | {n} |" for i, n in instituicoes.items())
    licencas = df["direitos"].value_counts().head(8)
    linhas_lic = "\n".join(f"| {l or '(não informado)'} | {n} |" for l, n in licencas.items())
    fontes = df.apply(lambda r: _fonte(r.get("id_bdtd", ""), r.get("url_registro", "")), axis=1)
    linha_fontes = "; ".join(f"{f} ({n})" for f, n in fontes.value_counts().items())

    texto = f"""# DATACARD — Corpus BDTD: {area}

**Versão:** {date.today().isoformat()}
**Fontes de onde os documentos vieram:** {linha_fontes}
**Coletado por:** {cfg.get_path("projeto.instituicao")} — contato: {cfg.get_path("projeto.contato")}

## 1. Composição

| Métrica | Valor |
|---|---|
| Documentos no corpus final | {len(df)} |
| Palavras totais | {palavras:,} |
| Palavras por documento (mediana) | {int(df['palavras'].median()) if 'palavras' in df and len(df) else 0} |
| Período coberto | {int(anos.min()) if len(anos) else '-'}–{int(anos.max()) if len(anos) else '-'} |
| Instituições distintas | {df['instituicao'].nunique()} |
| Idioma | português (filtro com limiar de confiança) |

### Divisão

| Split | Documentos |
|---|---|
""" + "\n".join(f"| {k} | {v} |" for k, v in por_split.items()) + f"""

### Principais instituições

| Instituição | Documentos |
|---|---|
{linhas_inst}

### Direitos declarados na fonte

| Direitos | Documentos |
|---|---|
{linhas_lic}

## 2. Produtos gerados

| Produto | Conteúdo |
|---|---|
| `pretreino/*.jsonl` | {produtos.get('pretreino')} — documento inteiro, campo `text` |
| `sft/*.jsonl` | {produtos.get('sft')} — pares instrução/resposta no formato `messages` |
| `rag/corpus_rag.parquet` | {produtos.get('rag', {}).get('chunks', 0)} chunks de {cfg.get_path('curated.rag.tamanho_chunk_palavras')} palavras (sobreposição {cfg.get_path('curated.rag.sobreposicao_palavras')}) |
| `benchmark/` | {produtos.get('benchmark')} |

## 3. Como foi construído

`Raw` (metadado cru da fonte + PDF original) → `Staging` (tabelas Parquet,
validação de integridade) → `Processed` (extração, normalização,
anonimização, filtros de qualidade, deduplicação) → `Curated` (este dataset).

Parâmetros efetivos em `config/config.yaml`; contagens de entrada, saída e
falha por etapa em `data/reports/`.

## 4. Tratamento aplicado

- **Padronização:** UTF-8/NFC, correção de mojibake (ftfy), ligaduras tipográficas;
  idioma (código ISO: `pt`, `en`…), tipo (`dissertação de mestrado` / `tese de
  doutorado`) e ano (inteiro entre 1800 e o ano corrente) em vocabulário fechado,
  com o valor original preservado em `<campo>_bruto`.
- **Normalização:** remoção de caracteres de controle, espaços Unicode, cabeçalho
  e rodapé repetidos entre páginas, números de página, hifenização de quebra de
  linha, entidades HTML, colapso de espaços em branco.
- **Anonimização:** e-mail e URL de perfil social; CPF, CNPJ, título de eleitor,
  PIS/PASEP e cartão SUS só quando o dígito verificador confere; telefone com DDD
  válido; CEP e RG. Links, DOI e ORCID ficam fora dos detectores numéricos (seus
  dígitos imitam documento). Placa de veículo desligada (colidia com nome de gene
  e sigla de estudo). Aplicada ao texto e também ao título e ao resumo usados no
  SFT e no benchmark. Estratégia: `{cfg.get_path('processed.anonimizacao.estrategia')}`.
- **Deduplicação:** exata (SHA-256 do texto normalizado), aproximada
  (MinHash+LSH, Jaccard ≥ {cfg.get_path('processed.deduplicacao.minhash_limiar_jaccard')})
  e interna (parágrafos repetidos no mesmo documento).
- **Descontaminação:** documentos de treino semelhantes a documentos de
  avaliação foram removidos do treino.

## 5. Limitações conhecidas

- **Nome de autor e orientador são preservados.** São dado bibliográfico
  público, parte da citação, e removê-los quebraria a proveniência. A
  anonimização atua sobre PII de terceiros no corpo do texto.
- **A anonimização é baseada em padrões e não é garantia.** PII escrita por
  extenso, em imagem sem OCR, ou em formato não previsto pode passar. Antes de
  publicar o corpus, faça uma auditoria manual amostral.
- **Direitos autorais.** Cada tese tem licença própria, definida pela
  instituição de origem. A coluna `direitos` preserva o que a fonte declarou;
  documentos sem acesso aberto declarado não têm o texto incluído. Uso além de
  pesquisa exige verificar a licença item a item.
- **Viés de cobertura.** O acervo reflete quem deposita no repositório e quais
  repositórios a coleta alcançou (ver "Instituições distintas" e "Período
  coberto" acima): com poucas instituições, o corpus fala pela produção delas,
  não pela área no país. Perdas de coleta declaradas em `data/reports/`.
- **Qualidade de OCR.** Trabalhos antigos digitalizados produzem texto com
  ruído mesmo após os filtros. A coluna `paginas_ocr` permite excluí-los.
- **Benchmarks automáticos medem recuperação e memória factual**, não domínio
  do conteúdo. Um benchmark de domínio exige curadoria humana.

## 6. Uso pretendido

Pesquisa acadêmica: pré-treino continuado e ajuste fino de modelos de
linguagem em português brasileiro técnico-científico, e sistemas de busca
semântica sobre produção acadêmica nacional.

**Não recomendado para:** qualquer uso que redistribua o texto integral das
teses sem verificar a licença individual de cada uma.
"""
    destino = dir_out / "DATACARD.md"
    destino.write_text(texto, encoding="utf-8")
    return destino


# --------------------------------------------------------------------------
def executar(cfg: Config) -> Relatorio:
    rel = Relatorio(camada="curated", area=cfg.get_path("projeto.area_rotulo", ""))
    dir_out = cfg.dir_camada("curated")

    try:
        df, textos = carregar_corpus(cfg)
    except FileNotFoundError as exc:
        rel.falha("camada", "processed_ausente", str(exc))
        rel.salvar(cfg.dir_relatorios())
        return rel

    rel.entradas["documentos_processed"] = len(df)
    if not len(df):
        rel.falha("camada", "corpus_vazio", "nenhum documento aprovado na camada Processed")
        rel.salvar(cfg.dir_relatorios())
        return rel

    df = dividir(df, cfg, textos)
    rel.metricas["split"] = df["split"].value_counts().to_dict()

    produtos = {
        "pretreino": gerar_pretreino(df, textos, dir_out, cfg),
        "sft": gerar_sft(df, textos, dir_out, cfg),
        "rag": gerar_rag(df, textos, dir_out, cfg),
        "benchmark": gerar_benchmarks(df, textos, dir_out, cfg),
    }
    rel.saidas.update(produtos)

    df.drop(columns=[c for c in ("motivos_reprovacao",) if c in df]).to_parquet(
        dir_out / "indice_corpus.parquet", index=False
    )
    datacard = gerar_datacard(cfg, df, produtos, dir_out)
    rel.saidas["datacard"] = str(datacard)

    log.info("camada Curated concluída em %s", dir_out)
    rel.salvar(cfg.dir_relatorios())
    return rel


if __name__ == "__main__":
    executar(Config.carregar())
