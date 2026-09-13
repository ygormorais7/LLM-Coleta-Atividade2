# bdtd-corpus

Pipeline em camadas que vai da coleta de teses e dissertações de **Saúde**
(BDTD/IBICT e repositórios institucionais de origem) até datasets prontos para
pré-treino continuado, fine-tuning, RAG e avaliação de modelos de linguagem em
português.

**Grupo 7** — Otávio da Conceição França, Ygor Morais, Eduardo Melo ·
Tópicos em Inteligência Artificial (DC/CCN072) · UFPI · Prof. Raimundo Moura

| Item do enunciado | Onde está |
|---|---|
| 1. Crawler da BDTD | `src/raw/fontes.py` e `src/raw/inventario.py` (inventário: OAI-PMH e inventário da BDTD), `src/raw/fulltext.py` (página do item → PDF), `src/raw/harvest.py` (download por cota) |
| 2. Arquitetura Raw → Staging → Processed → Curated | `src/raw/`, `src/staging/`, `src/processed/`, `src/curated/`, orquestradas por `run_pipeline.py` |
| 3. Tratamento na Processed | `src/processed/padroniza.py`, `clean.py` (normalização, anonimização, qualidade), `dedup.py`, `run.py` |
| 4. Produtos na Curated | `src/curated/build.py` → `pretreino/`, `sft/`, `rag/`, `benchmark/`; `src/curated/verificar_pii.py` |

Protocolo de coleta: `docs/PROTOCOLO_DE_COLETA.md`. Relatório da atividade:
`docs/RELATORIO_ATIVIDADE_02.md` (e `.pdf`).

---

## Começando

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# OCR (quase obrigatório para teses antigas)
sudo dnf install tesseract tesseract-langpack-por   # ou: apt install tesseract-ocr tesseract-ocr-por
pip install pytesseract Pillow

python -m pytest          # 128 testes, todos em diretório temporário: nenhum toca em data/
```

> **Cuidado:** `tests/gerar_dados_sinteticos.py` **apaga as quatro camadas de
> `data/`** para gerar uma camada Raw falsa. Só rode num clone sem dados reais.

Tudo que é decisão de projeto está em `config/config.yaml`.

---

## Como fazer uma coleta, na ordem

```bash
# 1. evidência do robots.txt de cada fonte (vai para data/reports/<area>/)
python -m src.raw.inventario descobrir --base https://repositorio.exemplo.br   # fonte OAI
python -m src.raw.inventario robots                                          # domínios do inventário BDTD

# 2. verificação pré-voo: para se houver bloqueio
python preflight.py

# 3. inventário (escolha o que se aplica)
python -m src.raw.inventario construir                     # colhe as fontes OAI e amostra
python -m src.raw.inventario janela --de 2026-02-25 --ate 2026-06-25 [--prefixo oai_dc]
python -m src.raw.inventario bdtd_csv                      # candidatos do inventário da BDTD

# 4. download, dentro do tmux (sobrevive à queda da sessão)
tmux new -s coleta
python run_pipeline.py --camadas raw

# 5. tratamento e produtos (local, sem rede)
python run_pipeline.py --camadas staging processed curated
```

O passo 5 termina com a **verificação de dados pessoais no Curated**: se sobrar
qualquer ocorrência, o `run_pipeline.py` sai com código 1. Rode também à mão:
`python -m src.curated.verificar_pii`.

---

## 1. De onde vem a lista (inventário)

`coleta.fonte_inventario: "inventario"` usa as fontes de `inventario.fontes`. O
resto do pipeline não muda quando a fonte muda.

**OAI-PMH do repositório de origem** (fonte principal: UFMG, set `com_1843_6`).
OAI-PMH é o protocolo feito para colheita por máquina. `metadata_prefix: dim`
preserva o qualificador do campo programa, que `oai_dc` perde; `ore` entrega a
URL do PDF e dispensa raspar a página do item.

- **Paginação profunda:** o DSpace devolve HTTP 500 em `resumptionToken` profundo
  (na UFMG, perto de 7.900 registros). `janela_dias` fatia a colheita por
  datestamp.
- **Janela que falha** é dividida ao meio até 1 dia. O que não se recupera é
  **declarado** no relatório.
- **Disjuntor:** 5 falhas seguidas sem registro novo interrompem a colheita.
- `inventario janela` recolhe só um intervalo e junta ao inventário os candidatos
  que faltavam, sem reamostrar.

**Inventário da BDTD exportado pelo grupo** (`inventario.fontes.bdtd_csv`).
Eduardo Melo montou o inventário da área pela API da BDTD: 183.718 fichas com a
URL do item no repositório de origem. `inventario bdtd_csv` aplica os filtros
deste projeto:

- **Direitos:** só acesso aberto com URL.
- **Escopo:**
  - inclusão por radical (`odontolog` pega "odontológico"); `medic` e `hospital`
    não são usados, porque casam com "medição" e "hospitalidade";
  - exclusão por **palavra inteira**.
- **Instituições excluídas:**
  - UFMG, que já vem pelo OAI;
  - UNIFESP, suspensa;
  - PUC-RS, cujo robots.txt veta robôs de IA;
  - UFSC, que tem desafio anti-robô.
- **Piloto:** lista de instituições e limite por instituição.

O arquivo não tem resumo; o escopo é checado de novo na Processed com o começo
do texto.

**Amostragem com cota e fila de reserva por estrato** (`ies` + faixa de ano): o
download consome a fila até fechar a cota daquele estrato, e a taxa de
resolução por estrato entra no relatório. Sem isso, estratos com repositório
fraco encolhem sozinhos e o viés fica invisível.

## 2. O que saber sobre a BDTD

**A BDTD tem metadado, não tem PDF.** O IBICT é agregador: o arquivo continua no
repositório da instituição. Toda coleta de texto tem dois saltos — inventário,
depois página do item no repositório de origem.

**O salto para o repositório resolve por metatag.** DSpace e TEDE emitem
`<meta name="citation_pdf_url">`. `fulltext.py` tenta essa metatag primeiro,
depois âncoras `/bitstream/` e `.pdf`, e por último a **API REST do DSpace 7**
(`/server/api`). O último passo existe porque há DSpace 7 que entrega só a
"casca" da página, sem link nenhum (UFRN). Outra armadilha real: metatag com
endereço interno do servidor (`http://localhost:4000/...`, na Fiocruz), que o
coletor troca pelo domínio da página.

**Armadilhas da API da BDTD** (documentadas por Eduardo Melo no projeto
G7-Atividade02-BDTD):
- a paginação trava na página 10 (teto de 1.000 registros por consulta);
- as facetas devolvem no máximo 30 valores;
- booleano dentro de `filter[]` devolve 0 em silêncio.

A saída dele é particionar a consulta por prefixo do identificador.

**A busca da interface é proibida a robôs** (`Disallow: /vufind/Search/`).
Este pipeline não usa a interface: usa OAI-PMH e o inventário pronto do grupo.

### Sobre ser um crawler decente

- **Ritmo por domínio:** 1 requisição a cada 2 s na fonte de metadados, 1 a cada
  3 s em cada repositório. Domínios diferentes andam em paralelo; dentro de um
  domínio o intervalo é sempre o do config.
- **`robots.txt` em todos os caminhos de rede:** respeitado, com `Crawl-delay`,
  na colheita OAI e no download, **a cada salto de redirecionamento**
  (`hdl.handle.net` → repositório final).
- **Letra e espírito:** quando divergem, vale o espírito. Repositório que veta
  robôs de IA não entra.
- **Proteção anti-robô:** página de desafio (Cloudflare etc.) é motivo de parar
  a coleta naquele domínio, não de contornar.
- **Identificação:** o User-Agent traz projeto, instituição e e-mail de contato.
- **Retomada:** o download é idempotente; reexecutar não rebaixa o que já está
  no disco.
- **Verificação antes de coletar:** `preflight.py` exige evidência de robots.txt
  para cada domínio e recusa ritmo acima do protocolo.

---

## 3. As camadas

```
FONTE (OAI-PMH dos repositórios + inventário da BDTD do grupo)
  │
  ├─ RAW ......... preservação: metadado cru e PDF byte a byte.
  │                Saída: inventario.jsonl, metadata/registros.jsonl, pdf/*.pdf, manifesto.jsonl
  │
  ├─ STAGING ..... organização: 4 tabelas Parquet, encoding acertado, tipo real
  │                do arquivo por magic bytes, integridade validada.
  │                Saída: documentos/autores/assuntos/arquivos.parquet
  │
  ├─ PROCESSED ... extração, padronização, normalização, anonimização,
  │                qualidade, escopo e deduplicação. A camada mais cara.
  │                Saída: texto/*.txt, documentos.parquet, metadados.parquet,
  │                       pii_relatorio.parquet, extracao_stats.jsonl
  │
  └─ CURATED ..... quatro produtos para quatro consumidores + verificação de PII.
                   Saída: pretreino/, sft/, rag/, benchmark/, DATACARD.md
```

Nenhuma camada modifica a anterior. Mudar um filtro exige só reprocessar a
partir da camada afetada, sem recoletar. A Processed só trata o que está no
Staging da rodada atual: texto de rodada anterior esquecido em disco é ignorado
e contado no relatório.

Cada camada escreve `data/reports/<area>/<camada>.json` com entradas, saídas,
métricas e **falhas tipadas**.

---

## 4. O pipeline de tratamento (Processed)

```
extração → normalização → anonimização → repetição interna → qualidade → escopo → deduplicação
                                     (+ padronização e anonimização dos metadados)
```

**Extração (`extract.py`).** PyMuPDF página a página; página quase sem texto é
tratada como imagem e, se a maioria for imagem, entra OCR (Tesseract, português,
com teto de páginas). Páginas e páginas com OCR vão para `extracao_stats.jsonl`,
reaproveitado quando a extração vem do cache.

**Normalização (`clean.py`).**
- **Texto e caracteres:** `ftfy` e NFC; ligaduras; caracteres de controle;
  espaços Unicode.
- **Ruído de layout:** cabeçalho e rodapé repetidos entre páginas; números de
  página; hifenização de quebra de linha; pontos de preenchimento de sumário;
  colapso de espaços.
- **Cortes:** pré-textuais até o RESUMO, e o material depois das referências ou
  anexos.

**Padronização (`padroniza.py`).** Idioma (código ISO), tipo (`dissertação de
mestrado` / `tese de doutorado`) e ano (1800 até o ano corrente) em vocabulário
fechado, com o valor original ao lado (`*_bruto`).

**Anonimização (`clean.py`).** Alvo: PII de terceiros no texto, no título e no
resumo. Autor e orientador são dado bibliográfico público e não são
anonimizados.

- **Detectores:**
  - e-mail e perfil de rede social;
  - CPF, CNPJ, **título de eleitor, PIS/PASEP e cartão SUS só com dígito
    verificador válido**;
  - telefone com DDD válido;
  - CEP;
  - RG (7 a 10 dígitos).
- **Links, DOI e ORCID ficam fora dos detectores numéricos:** seus dígitos
  imitavam documento.
- **Placa de veículo desligada:** colidia com nome de gene (`CYP2C19`) e sigla de
  estudo (`OMS-2008`).
- **Auditoria:** cada máscara vai para `pii_relatorio.parquet` com o trecho em
  volta **já mascarado**, e a Curated é verificada no fim.

**Qualidade.** Heurísticas no espírito Gopher/RefinedWeb calibradas para tese em
português:
- tamanho;
- proporção de texto alfabético, símbolos e tamanho médio de palavra;
- stopwords;
- linhas duplicadas e tokens curtos (OCR de tabela);
- idioma por votação em três janelas do miolo.

O relatório guarda a métrica **e** o motivo de cada reprovação.

**Escopo.** Exclusão de zootecnia/veterinária/agrárias por palavra inteira,
sobre título, programa, assuntos e resumo (ou o começo do texto). Motivo gravado:
`fora_de_escopo_zootecnia`.

**Deduplicação (`dedup.py`).**
- **Exata:** SHA-256 do texto normalizado.
- **Aproximada:** MinHash + LSH, Jaccard ≥ 0,80.
- **Interna:** parágrafo repetido no mesmo documento.

---

## 5. Produtos da Curated

| Produto | Formato | Para que serve |
|---|---|---|
| `pretreino/*.jsonl` | `{id, text, meta}` | pré-treino continuado |
| `sft/*.jsonl` | `{id, messages, meta}` | fine-tuning supervisionado |
| `rag/corpus_rag.parquet` | chunks de 500 palavras, sobreposição de 50, metadado embutido | busca semântica com citação da fonte |
| `benchmark/` | recuperação, múltipla escolha, perplexidade + README de pontuação | avaliação |
| `indice_corpus.parquet`, `DATACARD.md` | índice e ficha do corpus | documentação |

- **Metadados:** título e resumo usados no SFT e no benchmark vêm da Processed,
  anonimizados; o campo `fonte` diz de onde o documento veio de fato.
- **SFT:** os pares vêm de campos verificáveis (resumo, título, palavras-chave),
  não de um LLM. Resumo em inglês não entra nem na pergunta nem na resposta.
- **Split por grupo:** a divisão é por autor + programa, e o treino é
  **descontaminado** contra a avaliação por MinHash.
- **O RAG é gravado em lotes:** montar os ~150 mil chunks na memória derrubava o
  processo.
- **O que os benchmarks medem:** recuperação e memória factual sobre o acervo,
  **não** domínio do conteúdo. Benchmark de domínio exige perguntas escritas e
  revisadas por humanos.

---

## 6. Explorando o resultado

```python
import pandas as pd
d = pd.read_parquet('data/processed/saude/documentos.parquet')
print(d.loc[~d.no_corpus, 'motivos_reprovacao'].value_counts().head(15))   # por que saiu

pii = pd.read_parquet('data/processed/saude/pii_relatorio.parquet')
print(pii.groupby('tipo').size())
print(pii.sample(20)[['tipo', 'contexto']])                                # conferir falso positivo à mão
```

---

## 7. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `janela … falhou (500 Server Error)` na colheita OAI | defeito do servidor em registros daquele período | o pipeline divide a janela e declara a perda; teste `--prefixo oai_dc`; relate ao administrador |
| `colheita interrompida` após 5 falhas | disjuntor | não force: registre o incidente no protocolo |
| `robots.txt` que é página HTML de desafio | proteção anti-robô (Cloudflare) | exclua o domínio; não contorne |
| Muitos `pdf_nao_localizado` | repositório monta o link via JavaScript ou exige login | se for DSpace 7, a API REST já é tentada; `fallback_selenium` só como último recurso |
| `pdf_nao_localizado` em todo link `hdl.handle.net/<prefixo>/…` | servidor de handles da instituição fora do ar (HTTP 500, "Cannot Connect to Server") | retire a instituição; não insista |
| `bloqueado_ou_erro_rede` com a página do item carregando | metatag com endereço interno (`localhost`) | já corrigido em `fulltext._no_mesmo_site`; se voltar, olhe o `citation_pdf_url` da página |
| Verificação de PII falha só no RAG | texto do RAG diferente do pré-treino (linhas juntadas) | o RAG recorta o texto original; veja os `exemplos_mascarados` |
| `conteudo_nao_e_pdf` | repositório devolveu página de erro com HTTP 200 | comportamento correto: o arquivo foi descartado |
| `arquivos_brutos_orfaos_ignorados` no relatório | texto de rodada anterior que saiu da amostra | esperado; não entra no corpus |
| Verificação de PII no Curated falha | máscara que não pegou algum campo | veja `verificacao_pii_curated.json`; corrija o detector e reprocesse |
| Extração consumindo toda a RAM | `workers` alto demais | mantenha abaixo do número de núcleos |

---

## 8. Antes de entregar

- [ ] `python -m pytest` passando
- [ ] `projeto.contato` com e-mail real (vai no User-Agent)
- [ ] evidência de robots.txt de cada fonte em `data/reports/<area>/`
- [ ] `data/reports/*.json` das camadas e o `DATACARD.md` commitados — são a prova de auditoria
- [ ] leitura manual de amostra: textos, pares de SFT e `pii_relatorio.parquet`
- [ ] verificação de PII no Curated sem ocorrências
- [ ] protocolo com o registro de execução e os incidentes da rodada
- [ ] `data/` fora do Git (só relatórios e DATACARD entram)

---

## Aviso

Coleta para fins de pesquisa acadêmica. O direito sobre cada tese é da
instituição de defesa e do autor. Este pipeline só baixa texto de registros
marcados como acesso aberto e não redistribui PDF nem texto integral.
