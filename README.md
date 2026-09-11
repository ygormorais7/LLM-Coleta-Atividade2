# bdtd-corpus

Pipeline em camadas que vai da coleta de teses e dissertações na **BDTD/IBICT**
até datasets prontos para pré-treino continuado, fine-tuning, RAG e avaliação.

| Item do enunciado | Onde está |
|---|---|
| 1. Crawler da BDTD | `src/raw/bdtd_client.py`, `src/raw/fulltext.py`, `src/raw/harvest.py` |
| 2. Arquitetura Raw → Staging → Processed → Curated | `src/raw/`, `src/staging/`, `src/processed/`, `src/curated/` |
| 3. Tratamento na Processed | `src/processed/clean.py` (padronização, normalização, anonimização) e `src/processed/dedup.py` |
| 4. Produtos na Curated | `src/curated/build.py` → `pretreino/`, `sft/`, `rag/`, `benchmark/` |

---

## Começando

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# OCR (opcional, mas quase obrigatório para teses antigas)
sudo apt install tesseract-ocr tesseract-ocr-por
pip install pytesseract Pillow
```

Teste o pipeline **sem tocar na BDTD** primeiro:

```bash
python tests/gerar_dados_sinteticos.py     # cria uma camada Raw falsa
# baixe processed.qualidade.min_palavras para ~120 no config (os PDFs de teste são curtos)
python run_pipeline.py --camadas staging processed curated
```

Depois, para valer:

```bash
python run_pipeline.py --camadas raw          # coleta
python run_pipeline.py                        # as 4 camadas
```

Tudo que é decisão de projeto está em `config/config.yaml`. Não há número
mágico no código.

---

## 1. Escolhendo e configurando sua área

Cada grupo pega uma área no fórum. Depois, ache o **filtro Solr** que
corresponde a ela — o rótulo bonito da interface não serve para consultar a API:

```bash
# lista os valores possíveis de um campo e quantos registros cada um tem
python -m src.raw.bdtd_client facets --field format
python -m src.raw.bdtd_client facets --field dc.subject.cnpq.fl_str_mv --limit 60
python -m src.raw.bdtd_client facets --field institution --limit 40

# confere quantos registros a sua consulta devolve antes de coletar
python -m src.raw.bdtd_client total --filtro 'language:"por"'
```

Atalho: abra a BDTD no navegador, clique na sua área e **copie os parâmetros
`filter[]` da URL**. Cole em `coleta.filtros` no config.

> Comece com `max_registros: 500`. Rode o pipeline inteiro. Só depois zere o
> limite e deixe a coleta completa rodando.

---

## 1b. Estágio 1: de onde vem a lista

`coleta.fonte_inventario` escolhe a origem do inventário. O resto do pipeline
não muda quando você troca.

```bash
# 1. baixe os CSV em dadosabertos.capes.gov.br -> data/externo/capes/
# 2. descubra os conjuntos de um provedor OAI antes de fixar `set`
python -m src.raw.inventario identify --endpoint https://api.openaire.eu/oai_pmh
python -m src.raw.inventario sets     --endpoint https://api.openaire.eu/oai_pmh
# 3. construa o inventário (CAPES ⋈ OAI, reconciliado e amostrado)
python -m src.raw.inventario construir
python run_pipeline.py --camadas raw
```

**A moldura da CAPES não é a moldura da BDTD.** A CAPES lista tudo que foi
declarado à Sucupira, tenha ou não texto digital em algum lugar; o OAI de
agregador lista o que foi depositado e colhido. O segundo é subconjunto
próprio do primeiro. Por isso a taxa de resolução contra uma moldura CAPES é
pior e, principalmente, **desigual entre estratos**: IES grandes com
repositório maduro resolvem bem, IES pequenas e anos antigos resolvem mal.

A amostragem responde a isso com **cota + fila de reserva por estrato**: o
harvest consome a fila até fechar a cota daquele estrato, e a taxa de
resolução por estrato entra no relatório como característica do corpus. Sem
isso, os estratos fracos encolhem sozinhos e o viés fica invisível.

**Reconciliação é record linkage, não join.** Registros da CAPES praticamente
nunca têm handle ou DOI, então a chave é título + autor + ano + IES, com
blocking e limiar. O relatório guarda uma amostra de pares aceitos e de pares
no limite — **revise à mão** antes de confiar nas contagens por fonte.

**Declare a taxonomia.** `capes.area_avaliacao`, `capes.area_conhecimento` e
a faceta de navegação da BDTD são três classificações diferentes e nenhuma
reproduz o número da outra. O inventário registra qual você usou e falha o
relatório se você não declarar.

## 2. As três coisas que você precisa saber sobre a BDTD

**A BDTD tem metadado, não tem PDF.** O IBICT é agregador: coleta título,
autor, resumo e assunto via OAI-PMH dos repositórios das universidades, mas o
arquivo continua na instituição de defesa. Por isso a coleta tem **dois
saltos** — API da BDTD para o metadado, depois repositório institucional para
o texto completo. É aí que mora a maior parte da complexidade e das falhas.

**O salto para o repositório resolve por metatag, não por scraping frágil.**
DSpace e TEDE emitem `<meta name="citation_pdf_url">` (padrão Highwire Press,
usado pelo Google Scholar). É o caminho mais estável: sobrevive a mudança de
tema do repositório, ao contrário de seletor CSS. `fulltext.py` tenta essa
metatag primeiro e só depois cai para âncoras `/bitstream/` e `.pdf`.

**Solr não pagina infinitamente.** A janela é de ~10 mil resultados. Uma área
com 115 mil teses não sai de uma consulta só. `iterar()` fatia por ano de
defesa e, se algum ano ainda estourar, subdivide por instituição.

### Sobre ser um crawler decente

- rate limit **por domínio**: 1 req/2s na BDTD, 1 req/3s em cada repositório;
- `robots.txt` consultado e respeitado;
- User-Agent identifica projeto, instituição e e-mail de contato;
- retry com backoff exponencial, respeitando `Retry-After` em HTTP 429;
- download idempotente — reexecutar não rebaixa o que já está no disco.

Se as respostas vierem em HTML com *"Aguarde um momento enquanto validamos sua
conexão"*, você bateu na proteção anti-bot. Baixe
`requisicoes_por_segundo`, rode fora do horário de pico, e só então considere
`fallback_selenium: true`. Selenium é ~20x mais lento e come memória — use
como último recurso, não como padrão.

---

## 3. As camadas

```
FONTE (BDTD + repositórios)
  │
  ├─ RAW ......... preservação. A resposta da API vai crua para o disco, o PDF
  │                vai byte a byte. Nada é limpo, convertido ou renomeado.
  │                Saída: metadata/registros.jsonl, pdf/*.pdf, manifesto.jsonl
  │
  ├─ STAGING ..... organização. JSONL vira 4 tabelas Parquet, encoding dos
  │                metadados é acertado, o tipo real de cada arquivo é
  │                detectado por magic bytes, integridade é validada.
  │                Saída: documentos/autores/assuntos/arquivos.parquet
  │
  ├─ PROCESSED ... enriquecimento e filtragem. Extração de texto, tratamento
  │                completo, deduplicação. A camada mais cara do pipeline.
  │                Saída: texto/*.txt + documentos.parquet com as métricas
  │
  └─ CURATED ..... moldagem. Quatro produtos para quatro consumidores.
                   Saída: pretreino/, sft/, rag/, benchmark/, DATACARD.md
```

Nenhuma camada modifica a anterior. Cada uma lê e gera artefatos novos. É isso
que permite mudar um filtro de qualidade e reprocessar da Processed sem
recoletar 100 mil registros.

Cada camada escreve `data/reports/<area>/<camada>.json` com entradas, saídas,
métricas e **falhas tipadas**. Nada é silenciado: se um documento sumiu entre
duas camadas, o relatório diz qual e por quê.

---

## 4. O pipeline de tratamento (Processed)

Ordem obrigatória, e cada passo tem motivo para estar onde está:

```
extração → NORMALIZAÇÃO → ANONIMIZAÇÃO → repetição interna → QUALIDADE → DEDUPLICAÇÃO
```

Filtrar antes de normalizar reprova documento bom por mojibake. Anonimizar
antes de normalizar faz o regex de CPF errar por causa de espaço Unicode e
hifenização. Deduplicar antes de normalizar faz textos idênticos parecerem
diferentes. Deduplicar antes de filtrar gasta MinHash em lixo de OCR.

### Extração (`extract.py`)

PyMuPDF página a página; páginas com pouquíssimo caractere são marcadas como
imagem; se a maioria das páginas for imagem, entra OCR com Tesseract em
português — com teto de páginas, para não gastar 40 minutos numa tese
digitalizada inteira. Docling disponível como motor alternativo quando
estrutura importa mais que velocidade.

Paralelismo em `ProcessPoolExecutor`: parsing de PDF e OCR são CPU-bound.
(A coleta, que é I/O-bound, usa `ThreadPoolExecutor` — thread resolve espera
de rede sem o custo de memória de processos separados.)

### Padronização e normalização (`clean.py`, 9 etapas)

1. encoding e mojibake (`ftfy`), ligaduras tipográficas, NFC
2. `U+2028`/`U+2029` → `\n` (quebram tokenizador)
3. caracteres de controle invisíveis
4. variantes de espaço Unicode → espaço ASCII
5. **cabeçalho e rodapé repetidos entre páginas** — linha curta que aparece na
   borda de ≥60% das páginas é layout, não conteúdo
6. números de página soltos
7. hifenização de quebra de linha (`arqui-\ntetura` → `arquitetura`)
8. entidades HTML residuais
9. colapso de espaços e linhas em branco

Mais um corte estrutural: pré-textuais (capa, ficha catalográfica, folha de
aprovação, dedicatória, agradecimentos) são descartados até o `RESUMO`. São
ruído altamente repetitivo e cheio de nome de terceiro.

### Anonimização

CPF, CNPJ, e-mail, telefone, CEP, RG, cartão SUS, título de eleitor,
PIS/PASEP, placa e URLs de perfil social. Opcionalmente NER de nomes (spaCy).

Dois detalhes que fazem diferença:

**CPF e CNPJ são validados pelo dígito verificador antes de mascarar.** Sem
isso, todo número de processo, código de tabela e identificador experimental
com formato parecido vira `[CPF]` e o texto é destruído.

**Autor e orientador NÃO são anonimizados.** São dado bibliográfico público —
a tese é publicada com o nome deles, é assim que se cita, e vivem nos
metadados, não no corpo. Remover quebraria a proveniência do corpus sem ganho
de privacidade. O alvo real é PII de **terceiros** dentro do texto:
participante de entrevista, paciente, documento em anexo, termo de
consentimento digitalizado.

### Filtros de qualidade

Heurísticas no espírito de Gopher/RefinedWeb, calibradas para tese em
português: tamanho, proporção de palavras alfabéticas, excesso de símbolos,
tamanho médio de palavra, contagem de stopwords em português, proporção de
linhas duplicadas e idioma com limiar de confiança.

Perder boa parte dos documentos aqui é esperado e desejável. O que não é
aceitável é perder sem saber por quê — por isso o relatório guarda a métrica
**e** o motivo de reprovação de cada documento.

### Deduplicação (`dedup.py`)

Três níveis, porque duplicata aparece de três jeitos:

- **exata** — o mesmo trabalho coletado de dois repositórios. SHA-256 do texto
  normalizado.
- **aproximada** — mesma tese com folha de aprovação diferente, ou reextraída
  com OCR: 98% igual, hash diferente. MinHash + LSH, Jaccard ≥ 0.80, sem
  comparar N² pares.
- **interna** — sumário que reaparece, tabela repetida em anexo. Parágrafos
  duplicados dentro do mesmo documento.

Duplicata em corpus de pré-treino é o defeito mais caro que existe: o modelo
memoriza em vez de generalizar, e se um documento cai metade no treino e
metade no teste, o benchmark passa a medir memorização.

---

## 5. Produtos da Curated

| Produto | Formato | Para que serve |
|---|---|---|
| `pretreino/*.jsonl` | `{id, text, meta}` | pré-treino continuado (HF datasets, nanotron, litgpt) |
| `sft/*.jsonl` | `{id, messages, meta}` | fine-tuning supervisionado |
| `rag/corpus_rag.parquet` | chunks de 500 palavras, overlap 50 | indexação vetorial |
| `benchmark/` | 3 conjuntos + README de pontuação | avaliação |
| `DATACARD.md` | composição, parâmetros, limitações | documentação do dataset |

**Chunks são desnormalizados de propósito.** Cada chunk carrega título, autor,
instituição, programa, ano e URL. O resultado da busca precisa ser
autocontido, sem JOIN com outra tabela para saber de que tese veio o trecho.

**Os pares de SFT são derivados de campos verificáveis** (resumo, título,
palavras-chave), não gerados por um LLM. Assim você não destila alucinação
para dentro do dataset. Se depois quiser instruções mais ricas via LLM, faça
revisão humana amostral e registre isso no DATACARD.

**Os benchmarks são três:**

- **recuperação** — o resumo é a consulta, o documento é o gold. Reporte
  recall@5, recall@10 e MRR.
- **múltipla escolha** — 4 alternativas, gabarito vindo do registro
  bibliográfico (sem alucinação possível). Baseline aleatório: 25%.
- **perplexidade** — holdout para medir antes/depois do pré-treino continuado.

Honestidade sobre o que eles medem: recuperação e memória factual sobre o
acervo, **não** domínio do conteúdo. Um benchmark de domínio exige perguntas
escritas e revisadas por humanos. Vale dizer isso na apresentação.

### Split com anti-vazamento

A divisão é **por grupo (autor + programa)**, não por documento. Se o mesmo
orientando tem dissertação e tese, ou se o mesmo laboratório produz trabalhos
com metodologia idêntica, dividir por documento vaza estilo e conteúdo.

Depois do split, o treino é **descontaminado** contra o conjunto de avaliação
por MinHash. Documento de treino parecido demais com um de teste sai do
treino, não do teste.

---

## 6. Explorando o resultado

```python
import duckdb
duckdb.sql("""
  SELECT meta_instituicao, count(*) chunks, count(distinct doc_id) teses
  FROM 'data/curated/<area>/rag/corpus_rag.parquet'
  GROUP BY 1 ORDER BY 2 DESC LIMIT 15
""").show()
```

```python
# por que documentos foram reprovados?
import pandas as pd
d = pd.read_parquet('data/processed/<area>/documentos.parquet')
print(d[~d.aprovado_qualidade].motivos_reprovacao.value_counts())
```

---

## 7. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `RespostaInesperada: A BDTD devolveu HTML` | proteção anti-bot | baixe `requisicoes_por_segundo`, rode fora do pico, considere Selenium |
| `resultCount` alto mas coleta para em ~10 mil | janela do Solr | mantenha `particionar_por_ano: true` |
| Muitos `pdf_nao_localizado` | repositório monta o link via JS, ou exige login | ative `fallback_selenium`; alguns são realmente inacessíveis |
| `conteudo_nao_e_pdf` | repositório devolveu página de erro com HTTP 200 | comportamento correto — o arquivo foi descartado, veja o relatório |
| Tudo reprovado por `linhas_repetitivas` | texto muito repetitivo, ou OCR ruim | confira `data/processed/<area>/texto_bruto/` antes de mexer no limiar |
| `texto_insuficiente` em massa | PDFs escaneados sem camada de texto | ative o OCR e instale `tesseract-ocr-por` |
| Extração consumindo toda a RAM | `workers` alto demais | mantenha abaixo do número de núcleos |

---

## 8. Antes de entregar

- [ ] área registrada no fórum e `area_rotulo`/`area_slug` batendo com ela
- [ ] `projeto.contato` com um e-mail real (vai no User-Agent)
- [ ] pipeline testado com dados sintéticos antes da coleta real
- [ ] `data/reports/*.json` das 4 camadas commitados — são a prova de auditoria
- [ ] `DATACARD.md` revisado à mão (as limitações genéricas precisam virar as
      limitações reais **do seu** corpus)
- [ ] auditoria manual de ~30 documentos: a anonimização pegou tudo? a
      extração está legível?
- [ ] licença conferida: a coluna `direitos` diz o que a fonte declarou, e
      cada tese tem licença própria. Redistribuir texto integral exige
      verificar item a item.
- [ ] `data/` fora do Git (só os relatórios entram)

---

## Aviso

Coleta para fins de pesquisa acadêmica. A BDTD agrega metadados; o direito
sobre cada tese é da instituição de defesa e do autor. Este pipeline preserva
o campo de direitos declarado na fonte e, por padrão, só baixa texto de
registros marcados como acesso aberto — mas isso não substitui verificar a
licença antes de redistribuir qualquer coisa.
