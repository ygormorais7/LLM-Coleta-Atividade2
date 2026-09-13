# Relatório — Atividade 02: pipeline de dados de teses e dissertações de Saúde

**Grupo 7:** Otávio da Conceição França, Ygor Morais, Eduardo Melo  
**Disciplina:** Tópicos em Inteligência Artificial (DC/CCN072) — UFPI — Prof. Raimundo Santos Moura  
**Data:** 13/09/2026  
**Código:** repositório `bdtd-corpus` (este relatório está em `docs/`)

> **Como ler este relatório.** As seções 1 a 6 explicam como o pipeline
> funciona, na ordem em que o dado passa por ele. A seção 7 mostra como a
> qualidade foi verificada e quais defeitos isso revelou. A seção 8 registra os
> incidentes e as perdas da coleta. A seção 9 traz os números finais, e a 10, as
> limitações. O protocolo de coleta completo está em
> `docs/PROTOCOLO_DE_COLETA.md`; aqui ele aparece resumido na seção 3.

---

## Resumo

Construímos um pipeline em quatro camadas (Raw → Staging → Processed →
Curated) que vai da coleta de teses e dissertações de Saúde até datasets de
pré-treino continuado, fine-tuning, RAG e avaliação.

- **Coleta:** 3.596 PDFs de acesso aberto. 3.477 vêm da UFMG, pelo OAI-PMH; 119
  vêm de um piloto com a UFRN e a Fiocruz, usando o inventário da BDTD exportado
  pelo grupo (183.718 fichas). A coleta respeita `robots.txt`, `Crawl-delay` e 1
  requisição a cada 3 s por repositório. PUC-RS, UFSC e UFPR foram excluídas
  (veto a robôs de IA, desafio anti-robô e servidor fora do ar).
- **Corpus final:** 2.951 documentos, 72,0 milhões de palavras, 3
  instituições. Foram 4.937 ocorrências de dados pessoais mascaradas.
- **Produtos:** pré-treino com 2.951 documentos (treino, validação e teste
  separados por autor + programa); 978 pares de fine-tuning tirados de campos
  verificáveis, sem LLM; 155.312 trechos para RAG; 784 itens de benchmark.
- **Verificação final de dados pessoais no Curated:** **0 ocorrências** nos 11
  arquivos. Numa rodada anterior, essa mesma verificação parou o pipeline com
  erro e revelou um vazamento real (defeito 13).
- **Qualidade:** 128 testes automáticos e leitura manual a cada rodada. A
  leitura achou 15 defeitos, quase todos invisíveis nas métricas, e todos foram
  corrigidos (seção 7). Entre eles: ~1.900 máscaras falsas que apagavam DOI e
  nome de gene, telefones reais escapando da anonimização, pares de fine-tuning
  com a resposta copiada na pergunta e 10 teses de Saúde excluídas como zootecnia.
- **Perdas declaradas:** ~520 registros de uma janela da UFMG com falha no
  servidor; UFPR fora do ar. A meta de 20 mil PDFs não foi atingida nesta
  entrega (seção 10).

---

## 1. O enunciado e onde cada parte está

| Item pedido | O que foi feito | Onde está no código |
|---|---|---|
| 1. Crawler da BDTD para a área de Saúde | Inventário por OAI-PMH e pelo inventário da BDTD exportado pelo grupo; da página do item até o PDF; download com cota por estrato | `src/raw/fontes.py`, `src/raw/inventario.py`, `src/raw/fulltext.py`, `src/raw/harvest.py` |
| 2. Arquitetura Raw → Staging → Processed → Curated | Quatro camadas; cada uma lê a anterior e nunca a modifica | `src/raw/`, `src/staging/`, `src/processed/`, `src/curated/`, `run_pipeline.py` |
| 3. Processed: padronização, normalização, deduplicação e anonimização | Extração com OCR, normalização, padronização de metadados, anonimização com auditoria, filtros de qualidade e de escopo, deduplicação exata e aproximada | `src/processed/` |
| 4. Curated: pré-treino continuado, fine-tuning, RAG e benchmarks | Quatro produtos, divisão por grupo, descontaminação e verificação final de dados pessoais | `src/curated/` |

Tudo que é decisão de projeto (fontes, filtros, ritmo, limiares) está em
`config/config.yaml`. Cada camada grava `data/reports/saude/<camada>.json` com
entradas, saídas, métricas e falhas por tipo.

---

## 2. Visão geral

```
FONTES  OAI-PMH do repositório da UFMG  +  inventário da BDTD exportado pelo grupo
  │
  ├─ RAW ......... guarda o que veio da fonte, sem mexer: metadado cru e PDF byte a byte
  ├─ STAGING ..... organiza: tabelas Parquet, codificação acertada, tipo real do arquivo
  ├─ PROCESSED ... trata: extrai o texto, limpa, padroniza, anonimiza, filtra, deduplica
  └─ CURATED ..... entrega: pré-treino, fine-tuning (SFT), RAG, benchmarks + verificação de PII
```

**Por que camadas.** Trocar um filtro ou corrigir um detector não exige baixar
nada de novo: reprocessa-se a partir da camada afetada. Isso foi usado várias
vezes neste trabalho (seção 7): todos os consertos de tratamento foram aplicados
sobre os mesmos PDFs, sem nenhuma requisição nova.

**Comandos.**

```bash
python -m pytest                          # testes (nenhum toca em data/)
python preflight.py                       # antes de coletar; para se houver bloqueio
python -m src.raw.inventario construir    # inventário pelas fontes OAI
python -m src.raw.inventario bdtd_csv     # candidatos do inventário da BDTD
python run_pipeline.py --camadas raw      # download (dentro do tmux)
python run_pipeline.py --camadas staging processed curated    # local
```

---

## 3. Coleta (camada Raw)

### 3.1 A BDTD tem ficha, não tem PDF

A BDTD (IBICT) é um **agregador**: guarda a ficha de cada trabalho e aponta para
o repositório da universidade, onde o PDF está. Toda coleta de texto tem, então,
dois saltos: **(1) montar a lista** de trabalhos (inventário) e **(2) ir à
página de cada trabalho no repositório de origem** e achar o PDF.

### 3.2 Montar a lista: duas fontes

**Fonte 1 — OAI-PMH da UFMG (principal).** OAI-PMH é o protocolo feito para
máquinas colherem metadados de repositórios. Colhemos o conjunto `com_1843_6`
(Ciências da Saúde) no formato `dim`, que preserva o campo "programa", e pedimos
o formato `ore`, que já entrega o endereço do PDF.

- O DSpace da UFMG devolve erro HTTP 500 quando a paginação vai fundo; por isso a
  colheita é fatiada em janelas de datas (`janela_dias`).
- Uma janela que falha é **dividida ao meio**, até 1 dia; o que não se recupera
  é **declarado** no relatório (seção 8).
- **Disjuntor:** 5 falhas seguidas sem registro novo interrompem a colheita.

**Fonte 2 — inventário da BDTD exportado pelo grupo.** Eduardo Melo montou, no
projeto G7-Atividade02-BDTD, o inventário da área inteira pela **API** da BDTD
(`/vufind/api/v1/search`): 183.718 fichas com a URL do item no repositório de
origem. O trabalho dele também documentou armadilhas da API, que registramos
com o devido crédito:

- a paginação trava na página 10 (no máximo 1.000 registros por consulta);
- as facetas devolvem no máximo 30 valores;
- operador booleano dentro de `filter[]` devolve 0 resultados, sem erro.

A saída dele foi fatiar a consulta por prefixo do identificador. Reaproveitar o
arquivo pronto **não gera nenhuma requisição nova à BDTD**. Sobre ele aplicamos
os filtros deste projeto (`python -m src.raw.inventario bdtd_csv`):

| Filtro | Regra |
|---|---|
| Direitos | só acesso aberto com URL |
| Escopo (inclusão) | radicais sobre título e assuntos: `odontolog` pega "odontológico". `medic` e `hospital` **não** são usados: casam com "medição" e "hospitalidade" (uma tese de gastronomia tinha sido rotulada como de Saúde por isso) |
| Escopo (exclusão) | vocabulário de zootecnia e veterinária, **por palavra inteira** |
| Instituições | exclui UFMG (já vem pelo OAI), UNIFESP (suspensa), PUC-RS e UFSC (seção 3.5) |

Aplicado ao arquivo inteiro, o funil dá: 183.718 fichas → 160.801 com acesso
aberto e link → 155.537 fora da UFMG → ~71 mil de Saúde pelos radicais.

### 3.3 Amostragem com cota por estrato

Cada candidato pertence a um **estrato** (instituição + faixa de 5 anos). O
download percorre a fila de cada estrato até fechar a cota daquele estrato, e a
taxa de sucesso de cada um vai para o relatório. Sem isso, estratos de
repositórios que falham encolheriam em silêncio, e o viés ficaria invisível.

### 3.4 Da página do item até o PDF

`src/raw/fulltext.py` tenta, em ordem:

1. a metatag `citation_pdf_url` (padrão usado pelo Google Acadêmico; DSpace e TEDE emitem);
2. links `/bitstream/` ou `/bitstreams/` terminados em `.pdf`;
3. qualquer link `.pdf` da página;
4. **a API REST do DSpace 7** (`/server/api`): item → pacote `ORIGINAL` → primeiro PDF.

O item 4 e um ajuste no item 1 nasceram do diagnóstico do piloto (seção 8.3):
a UFRN serve só a "casca" da página, sem nenhum link, e a Fiocruz publica a
metatag com o endereço interno `http://localhost:4000/...`, que o coletor agora
troca pelo domínio público da página.

O arquivo só é gravado se começar com `%PDF` (página de login ou de erro com
HTTP 200 é descartada) e se tiver até 120 MB. O download é idempotente: rodar de
novo não baixa o que já está no disco.

### 3.5 Conduta de rede (protocolo de coleta, resumido)

| Regra | Como está implementada |
|---|---|
| Identificação | User-Agent com projeto, instituição e e-mail de contato |
| `robots.txt` | consultado e respeitado por domínio, **inclusive `Crawl-delay`**, na colheita OAI e no download |
| Ritmo | 1 requisição a cada 2 s na fonte de metadados; 1 a cada 3 s **por repositório** (ou o `Crawl-delay`, se maior). Repositórios diferentes andam em paralelo; dentro de um mesmo repositório o intervalo nunca diminui (o limitador reserva o próximo horário livre de cada domínio) |
| Redirecionamento | seguido à mão: cada salto (`hdl.handle.net` → repositório final) passa pelo `robots.txt` e pelo ritmo **do domínio de destino** |
| Letra e espírito | quando divergem, vale o espírito. A busca da interface da BDTD (`Disallow: /vufind/Search/`) não é usada. A PUC-RS permite `*` mas proíbe nominalmente robôs de IA (GPTBot, ClaudeBot, CCBot…): foi **excluída**, porque o uso deste corpus é treino de modelo |
| Proteção anti-robô | motivo para parar, não para contornar: a UFSC responde `/robots.txt` com desafio do Cloudflare e foi **excluída** |
| Antes de coletar | `pytest` + `preflight.py`, que bloqueia sem contato, sem evidência de `robots.txt` de cada domínio ou com ritmo acima do protocolo |
| Critérios de parada | HTTP 429/500/503 persistente num domínio; bloqueio ou desafio anti-robô; contato de administrador; taxa de erro acima de 30% num domínio |
| Evidência | o `robots.txt` de cada domínio, como estava no dia, fica em `data/reports/saude/evidencia_robots_*.json` |

A coleta roda dentro do `tmux`, para sobreviver à queda da sessão.

---

## 4. Staging

`src/staging/organize.py` transforma o JSONL cru em quatro tabelas Parquet
(`documentos`, `autores`, `assuntos`, `arquivos`), corrige codificação, confere o
tipo real de cada arquivo pelos primeiros bytes (e não pela extensão) e valida a
integridade (hash, tamanho). Nada é descartado aqui: a Staging organiza, a
Processed decide.

---

## 5. Tratamento (camada Processed)

```
extração → normalização → anonimização → qualidade → escopo → deduplicação
         (+ padronização e anonimização do título e do resumo)
```

**A ordem não é arbitrária.** Filtrar antes de normalizar reprova documento bom
por causa de codificação quebrada. Anonimizar antes de normalizar faz o detector
de CPF errar por causa de hifenização e de espaços Unicode.

### 5.1 Extração

PyMuPDF página a página. Página quase sem texto é tratada como imagem; se a
maioria das páginas for imagem, entra OCR (Tesseract, português). O número de
páginas e de páginas com OCR vai para `extracao_stats.jsonl` e é reaproveitado
quando o texto já está em cache.

### 5.2 Normalização

- **Caracteres:** `ftfy` (texto com codificação quebrada), forma Unicode NFC,
  ligaduras (`ﬁ` → `fi`), caracteres de controle e espaços especiais.
- **Ruído de layout:** cabeçalho e rodapé repetidos entre páginas, número de
  página, hifenização de fim de linha, pontilhado de sumário.
- **Cortes:** tudo antes do RESUMO (capa, ficha catalográfica, agradecimentos) e
  o que vem depois das referências (anexos, onde ficam termos de consentimento
  assinados).

### 5.3 Padronização dos metadados

O mesmo campo chegava escrito de várias formas: o idioma aparecia como
"Português" (1.879), "por" (1.727), "eng" (21), "Inglês", "fra" e "N/A".
`src/processed/padroniza.py` leva cada campo a um vocabulário fechado e guarda o
original ao lado (`<campo>_bruto`):

| Campo | Padrão |
|---|---|
| idioma | código ISO: `pt`, `en`, `es`, `fr`… |
| tipo | `dissertação de mestrado` / `tese de doutorado` (legível, porque entra no texto das instruções do SFT) |
| ano | inteiro entre 1800 e o ano corrente; fora disso, vazio |

### 5.4 Anonimização

**Alvo:** dados pessoais **de terceiros** no texto, no título e no resumo.
Autor e orientador são dado bibliográfico público e não são anonimizados.

| Detector | Regra |
|---|---|
| E-mail, perfil de rede social | padrão textual |
| CPF, CNPJ, título de eleitor, PIS/PASEP, cartão SUS | **só com dígito verificador válido** (título de eleitor com a regra do TSE e UF 01–28) |
| Telefone | DDD válido (sem zero), fixo começando com 2–5, celular com 9; intervalo de anos (`2008-2009`) recusado; quebra de linha aceita como separador só depois de `(DD)` ou `+55 DD` |
| CEP, RG | formato; RG com 7 a 10 dígitos |
| Links, DOI e ORCID | **protegidos**: ficam fora dos detectores numéricos |
| Placa de veículo | **desligada** |

Cada máscara vai para `pii_relatorio.parquet` com o trecho em volta **já
mascarado**, para que alguém confira à mão sem expor o dado.

**Precisão medida, não presumida.** Na primeira versão, recuperamos o valor
original por trás de cada máscara (comparando com o texto antes da limpeza) e
descobrimos que a maioria dos alarmes de alguns detectores era falsa:

| Detector | Máscaras antes → depois | O que era de verdade |
|---|---|---|
| Título de eleitor | 863 → 0 | ORCID (`0000-0002-8214`) e DOI |
| Placa | 478 → 0 (desligada) | gene `CYP2C19`; sigla + ano de estudo: `OMS-2008`, `GBD-2017` |
| Cartão SUS | 266 → 1 | DOI e código de setor censitário do IBGE |
| PIS/PASEP | 257 → 8 | DOI da revista Ciência & Saúde Coletiva |
| Telefone | 580 → 394 | quase todo real (comitê de ética, contato de pesquisador) |

Mascarar um DOI ou um nome de gene destrói conteúdo científico sem proteger
ninguém. Por isso a precisão foi corrigida **antes** de ampliar a coleta e antes
de ligar a verificação que para o pipeline (senão ela pararia por alarme falso).

### 5.5 Qualidade e escopo

- **Qualidade:** heurísticas no estilo Gopher/RefinedWeb, calibradas para tese em
  português: tamanho, proporção de texto alfabético e de símbolos, tamanho médio
  de palavra, stopwords, linhas repetidas, tokens curtos (sinal de OCR de tabela)
  e idioma por votação em três janelas do meio do texto. O motivo de cada
  reprovação fica registrado.
- **Escopo:** exclusão de zootecnia e veterinária por palavra inteira, sobre
  título, programa, assuntos e resumo (ou o começo do texto, quando não há
  resumo). A checagem roda de novo aqui, para que uma lista corrigida valha para
  o que já foi baixado. Antes da comparação, **expressões permitidas** são
  apagadas do texto: "pé equino", "soro fetal bovino", "dentina bovina" são Saúde,
  não zootecnia (defeito 15).

### 5.6 Deduplicação

- **Exata:** SHA-256 do texto normalizado.
- **Aproximada:** MinHash + LSH, similaridade de Jaccard ≥ 0,80.
- **Interna:** parágrafo repetido dentro do mesmo documento.

---

## 6. Produtos (camada Curated)

| Produto | Formato | Para quê |
|---|---|---|
| `pretreino/*.jsonl` | `{id, text, meta}` | pré-treino continuado de um modelo aberto já existente |
| `sft/*.jsonl` | `{id, messages, meta}` | fine-tuning para seguir instruções |
| `rag/corpus_rag.parquet` | trechos de 500 palavras com sobreposição de 50 e metadado | busca semântica com citação da fonte |
| `benchmark/` | recuperação, múltipla escolha, perplexidade + instruções de pontuação | avaliação |
| `indice_corpus.parquet`, `DATACARD.md` | índice e ficha do corpus | documentação |

- **Divisão por grupo:** treino, validação e teste são separados por autor +
  programa, e o treino é **descontaminado** contra a avaliação por MinHash.
- **SFT sem modelo gerador:** os pares vêm de campos verificáveis do próprio
  documento (resumo, título, palavras-chave e a introdução do texto). Nenhuma
  resposta é inventada por um LLM. Texto em inglês não entra nem na pergunta nem
  na resposta.
- **Metadados tratados:** título e resumo usados no SFT e no benchmark vêm da
  Processed, já padronizados e anonimizados.
- **Campo `fonte` honesto:** diz se o documento veio do OAI-PMH ou do inventário
  da BDTD, e de qual repositório.
- **RAG gravado em lotes:** montar ~150 mil trechos na memória derrubava o processo.
- **Verificação final de dados pessoais** (`src/curated/verificar_pii.py`): varre
  todos os produtos com os mesmos detectores; se encontrar qualquer ocorrência,
  grava `verificacao_pii_curated.json` e o `run_pipeline.py` **sai com erro**.
- **O que os benchmarks medem:** recuperação e memória sobre o acervo, **não**
  domínio do conteúdo de Saúde. Isso exigiria perguntas escritas e revisadas por
  especialistas.

---

## 7. Como a qualidade foi verificada

### 7.1 Testes automáticos

**128 testes** (`python -m pytest`, ~4 s), todos em diretório temporário:
nenhum toca em `data/`. Cada defeito corrigido ganhou um teste com o caso real que o revelou
(o código de procedimento `0101020058`, o gene `CYP2C19`, a "catequina", a
página-casca da UFRN, o `localhost:4000` da Fiocruz…). Os testes que acessam
"rede" usam servidor e sessão simulados.

### 7.2 Leitura manual

Regra do projeto: **métrica boa não é prova**. A cada reprocessamento foram
lidos textos tratados, pares de SFT e amostras do `pii_relatorio.parquet`.
A maioria dos defeitos abaixo foi achada assim. Os outros vieram de teste
automático, da verificação final ou de uma métrica incoerente. Nenhum apareceu
como uma métrica de qualidade ruim.

### 7.3 Defeitos achados e corrigidos

| # | Defeito | Como apareceu | Correção |
|---|---|---|---|
| 1 | Teses de zootecnia no corpus ("nutrição" casa com nutrição animal) | leitura de títulos | lista de exclusão aplicada também ao resumo |
| 2 | Filtro de acesso aberto não aplicado no caminho OAI: 16 documentos de acesso restrito quase entraram | leitura do manifesto | filtro no `harvest.py` |
| 3 | Zootecnia de novo: a lista só tinha plural masculino, e doença animal concorda no feminino ("raiva bovina") | leitura de títulos | todas as flexões; checagem repetida na Processed |
| 4 | Máscaras falsas: código de procedimento virando telefone, `PEG6000` virando placa, eixo de anos virando título de eleitor | leitura de textos | separador obrigatório; formato de placa estrito |
| 5 | Texto de rodada anterior reaprovado em silêncio | leitura do relatório | Processed restrita ao Staging atual |
| 6 | Páginas e OCR zerados quando o texto vinha do cache | métrica incoerente | histórico `extracao_stats.jsonl` |
| 7 | RAG estourando memória | processo morto 2 vezes | gravação em lotes |
| 8 | ~1.900 máscaras falsas (DOI, ORCID, gene) | valor original recuperado atrás de cada máscara | dígito verificador, proteção de links, placa desligada (seção 5.4) |
| 9 | Exclusão por trecho de palavra: "equina" casava dentro de "catequina" | teste automático | exclusão por palavra inteira |
| 10 | Título e resumo iam para o SFT **sem anonimização**; resumo em inglês dentro da pergunta | revisão do código da Curated | `metadados.parquet` anonimizado; trava de idioma na pergunta |
| 11 | No par "resuma", a resposta vinha **copiada dentro da pergunta**: o texto começa no RESUMO | leitura de pares de SFT | trecho tirado de depois do resumo; par descartado se houver sobreposição |
| 12 | Coletor não achava PDF em DSpace 7 sem renderização no servidor (UFRN) nem com metatag apontando para `localhost` (Fiocruz) | piloto com 0 de 180 | API REST do DSpace 7; troca do endereço interno |
| 13 | Telefone real quebrado em linha depois do DDD (`(31)↵3xxx-xxxx`) escapava da anonimização; e o RAG, ao juntar linhas com espaço, criava "telefones" e "CPFs" a partir de tabelas | **a verificação final do Curated parou o pipeline com erro** (35 ocorrências, todas no RAG) | quebra de linha aceita só depois de `(DD)` ou `+55 DD`; o RAG recorta o texto original, com as quebras. Auditoria da regra nova sobre os textos já tratados: 17 telefones a mais, todos reais |
| 14 | O conserto do defeito 11 criou outro: o trecho "depois do resumo" era o **ABSTRACT** (109 de 178 pares viraram tradução disfarçada), e a trava de idioma não via, porque "a", "as", "do" e "no" também são palavras inglesas | leitura de pares de SFT depois do reprocessamento | trecho a partir do título INTRODUÇÃO do corpo; trava compara português com inglês; palavras-chave sem código `CNPQ::`. No corpus real: 219 pares, 0 cópias, 1 em inglês |
| 15 | **10 teses de Saúde excluídas como zootecnia**: "saneamento" (saúde pública, 4 da Fiocruz), "pé equino" (ortopedia infantil), dentina bovina (odontologia in vitro, 2), soro fetal bovino, albumina sérica bovina e tripsina bovina (reagentes) | revisão à mão dos 42 excluídos, puxada por documentos da Fiocruz que não deviam ter saído | "saneamento" sai da lista; lista de **expressões permitidas**, apagadas do texto antes da checagem, na colheita e na Processed. Voltaram 8 ao corpus; as 2 de odontologia seguem fora por estarem em inglês |

O defeito 15 corrige uma afirmação anterior deste próprio trabalho. Os 39
excluídos da 3ª rodada tinham sido dados como "todos zootecnia" a partir dos
títulos. Só a leitura do termo que derrubou cada documento mostrou os falsos.
Ficaram excluídos, como casos de fronteira declarados, 2 estudos de vaccinia
bovina (vírus de gado que infecta ordenhadores) e 1 de doenças vesiculares de
bovinos.

O defeito 13 é o melhor argumento a favor da verificação final. O vazamento
existia também no pré-treino, mas lá a quebra de linha escondia o número dos
detectores. Só o RAG, que juntava as linhas, o deixou visível, e a verificação
barrou a entrega em vez de deixá-lo passar.

---

## 8. Incidentes e perdas declaradas

O registro completo, com data, número de requisições e evidência, está na seção
8 do protocolo. Resumo:

### 8.1 Janela de datas perdida na UFMG

Os registros com data entre 25/02/2026 e 25/06/2026 dão HTTP 500 no formato
`dim`, em qualquer recorte, até 1 dia.

- **Diagnóstico** (~10 requisições): a janela tem **755 registros**. No formato
  `oai_dc` a primeira página responde, mas a paginação volta a falhar.
- **Recuperação:** 235 registros → 13 de Saúde → **4 candidatos novos**. O
  disjuntor interrompeu sozinho após 5 falhas seguidas.
- **Perda declarada:** ~520 registros não colhidos (~50 de Saúde, pela proporção
  do resto da coleta), listados em `data/reports/saude/inventario_janela.json`.

### 8.2 Piloto 1: instituições excluídas antes de baixar

A leitura do `robots.txt` excluiu duas instituições: a PUC-RS (veta robôs de IA)
e a UFSC (desafio anti-robô do Cloudflare). O download foi interrompido antes de
gravar qualquer arquivo, e o inventário foi restaurado sem elas.

### 8.3 Piloto 2: 0 de 180 PDFs

UFRN, UFPR e Fiocruz, 60 candidatos cada: **nenhum PDF**. Pelo critério de parada
(taxa de erro acima de 30% num domínio), a expansão não seguiu. O diagnóstico
(1 registro por instituição, ~15 requisições, sem baixar PDF;
`data/reports/saude/diagnostico_piloto_bdtd.json`) achou três causas diferentes:

| Instituição | Sintoma | Causa | Decisão |
|---|---|---|---|
| UFRN | `pdf_nao_localizado` | DSpace 7 sem renderização no servidor: a página tem 1 KB e nenhum link | coletor passa a usar a API REST do DSpace 7 |
| Fiocruz | `bloqueado_ou_erro_rede` | a metatag aponta para `http://localhost:4000/bitstreams/.../download` (configuração do servidor deles) | endereço interno trocado pelo domínio público |
| UFPR | `pdf_nao_localizado` | `hdl.handle.net/1884/...` responde "Cannot Connect to Server" (HTTP 500): o servidor de handles da UFPR está fora do ar | **retirada**: não se insiste em serviço que está falhando |

### 8.4 Piloto 3: mesmos candidatos, depois da correção

Com o coletor corrigido e a UFPR retirada, os **mesmos 120 candidatos** foram
tentados de novo (nenhum candidato novo; testes e `preflight.py` antes):

| Instituição | Piloto 2 | Piloto 3 |
|---|---:|---:|
| UFRN (DSpace 7, via API REST) | 0 / 60 | **60 / 60** |
| Fiocruz (DSpace 7, metatag corrigida) | 0 / 60 | **59 / 60** |
| UFPR (servidor de handles fora do ar) | 0 / 60 | retirada |

Foram 473 MB em 22 minutos, sem nenhum erro de rede. A UFRN custa ~5
requisições por trabalho (página + API), no ritmo de 1 a cada 3 s. A lição para
a expansão: **cada família de repositório precisa ser pilotada antes**. Um
coletor que funciona em 3.477 PDFs da UFMG deu 0 em três repositórios
diferentes.

### 8.5 Outras

- **UNIFESP suspensa** desde a 1ª rodada: uma versão antiga do coletor não
  respeitava o `Crawl-delay: 15`; depois, conexão recusada.
- **Anhembi:** 2 links testados à mão pelo grupo não carregaram. A instituição
  tem 1 ficha no conjunto filtrado e não foi incluída no piloto.

---

## 9. Resultados

### 9.1 Coleta (Raw e Staging)

| Fonte | Candidatos | Bloqueados por direitos | PDFs obtidos |
|---|---:|---:|---:|
| UFMG, OAI-PMH (3ª rodada + 4 da janela recuperada) | 3.636 | 186 | 3.477 |
| Inventário da BDTD — UFRN (piloto) | 60 | — | 60 |
| Inventário da BDTD — Fiocruz (piloto) | 60 | — | 59 |
| **Total** | **3.756** | **186** | **3.596** |

O Staging organizou os 3.756 registros, 3.582 deles com arquivo. Os 14 arquivos
de rodadas anteriores sem registro atual foram apontados e ignorados.

### 9.2 Tratamento (Processed)

| Instituição | Textos tratados | No corpus final |
|---|---:|---:|
| UFMG | 3.463 | 2.845 |
| UFRN | 60 | 52 |
| Fiocruz | 59 | 54 |
| **Total** | **3.582** | **2.951** |

- **72,0 milhões de palavras**; mediana de 20.546 palavras por documento;
  340.069 páginas; 58 documentos precisaram de OCR.
- **Reprovados (631):** 628 por qualidade ou escopo e 3 duplicatas exatas;
  nenhuma duplicata aproximada. Os motivos mais comuns (um documento pode ter
  mais de um):

| Motivo | Documentos |
|---|---:|
| texto em inglês | 445 |
| linhas repetitivas (tabela, OCR ruim) | 150 |
| pouco texto alfabético | 42 |
| fora de escopo (zootecnia/veterinária) | 32 |
| OCR fragmentado | 11 |
| outros idiomas | 7 |

- **Dados pessoais mascarados:** 4.937 ocorrências, todas no texto (título e
  resumo não tinham nenhuma): e-mail 2.992, CEP 1.244, telefone 626, CPF 27,
  PIS/PASEP 24, perfil de rede social 19, CNPJ 4, cartão SUS 1.

### 9.3 Produtos (Curated)

| Produto | Treino | Validação | Teste | Total |
|---|---:|---:|---:|---:|
| Pré-treino (documentos) | 2.652 | 150 | 149 | 2.951 |
| Fine-tuning (pares) | 882 | 55 | 41 | 978 |
| RAG (trechos de 500 palavras) | — | — | — | 155.312 |
| Benchmark: recuperação / múltipla escolha / perplexidade | — | — | — | 292 / 292 / 200 |

- **Descontaminação:** nenhum documento de treino colidiu com a avaliação.
- **Pares de fine-tuning por tipo:** título a partir do resumo 267; explicação
  do trabalho a partir do título 265; resumo a partir do tema 167; resumo a
  partir da introdução 220; palavras-chave 59.
- **Conferência dos pares de resumo:** nenhuma resposta copiada na pergunta e 1
  pergunta em inglês, contra 186 cópias e 109 abstracts nas versões anteriores.
- **Documentos do piloto no fine-tuning:** 30 pares, todos de palavras-chave da
  Fiocruz (sem resumo, os outros tipos não se aplicam). As palavras-chave vêm
  como o repositório as declara, misturando português, inglês e espanhol.
- **Verificação final de dados pessoais:** 0 ocorrências nos 11 arquivos
  (pré-treino, fine-tuning, RAG, benchmarks e índice), com os mesmos detectores
  da Processed (`data/reports/saude/verificacao_pii_curated.json`).

---

## 10. Limitações e trabalho futuro

- **A meta de 20 mil PDFs não foi atingida.** A expansão depende de nova
  autorização de coleta e, pelo piloto, de adaptar o coletor a cada família de
  repositório. Com o ritmo do protocolo (1 requisição a cada 3 s por
  repositório) e ~71 mil candidatos, a estimativa é de dezenas de horas por
  repositório grande, em paralelo entre repositórios.
- **Poucas instituições.** O corpus fala pela produção da UFMG (e das
  instituições do piloto), não pela área no país.
- **Documentos do inventário da BDTD chegam sem resumo e sem programa** (o
  arquivo não traz esses campos) e com a instituição como sigla. Eles entram no
  pré-treino e no RAG, mas quase não geram pares de SFT (que dependem do
  resumo), e o escopo deles é checado pelo começo do texto. Buscar o resumo na
  API do repositório custaria mais requisições por documento.
- **Recall da anonimização não medido.** Precisão foi medida e corrigida. A
  leitura do relatório mostrou telefones que escapam, escritos sem hífen
  (`(31) 3xxxxxxx`) ou com `0XX` no DDD. Medir recall exige uma amostra rotulada
  à mão.
- **Quase-identificadores** (idade + doença rara + município + ano) permitem
  reidentificação sem nenhum CPF ou nome, e nenhum detector automático resolve
  isso. O corpus **não é declarado anonimizado**: declara-se o que foi detectado
  e mascarado.
- **Janela da UFMG:** recuperar os ~520 registros um a um (`GetRecord`) de um
  servidor que está falhando ficou para depois, com aviso ao administrador.
- **UFPR:** mapear o handle direto para o repositório (sem passar pelo servidor
  de handles) exige verificar o `robots.txt` desse outro domínio.
- **O fine-tuning é gerado por template de metadado** (título, resumo,
  palavras-chave, introdução), não por perguntas e respostas sobre o corpo do
  texto. Ensina o formato de instrução, não conteúdo profundo; perguntas de
  conteúdo exigiriam geração com revisão humana.
- **Benchmarks** medem recuperação, não conhecimento de Saúde.
- **Direitos autorais:** acesso aberto não é licença de redistribuição. Os dados
  não são publicados nem entregues; só código, relatórios e ficha do corpus.

---

## 11. Créditos

- **Eduardo Melo** (projeto G7-Atividade02-BDTD): inventário da BDTD da área de
  Saúde pela API (183.718 fichas) e documentação das armadilhas da API,
  reaproveitados como fonte 2 deste pipeline.
- **Grupo 7** — Otávio da Conceição França, Ygor Morais, Eduardo Melo.
