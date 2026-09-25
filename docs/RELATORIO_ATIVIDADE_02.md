# Relatório — Atividade 02: pipeline de dados de teses e dissertações de Saúde

**Grupo 7:** Eduardo Melo, Otávio França e Ygor Morais  
**Disciplina:** Tópicos em Inteligência Artificial (DC/CCN072) — UFPI — Prof. Raimundo Santos Moura  
**Data:** 25/09/2026  
**Repositório:** <https://github.com/ygormorais7/LLM-Coleta-Atividade2>  
**Código:** repositório `bdtd-corpus`. O protocolo de coleta completo está em `docs/PROTOCOLO_DE_COLETA.md`.

## Resumo

O grupo construiu um pipeline em quatro camadas (Raw → Staging → Processed →
Curated). Ele coleta teses e dissertações de Saúde e as transforma em dados
para pré-treino continuado, fine-tuning, RAG e avaliação de modelos de
linguagem em português.

- **Coleta:** 25.338 PDFs de acesso aberto, de 67 instituições, pelo OAI-PMH da
  UFMG e pelo inventário da BDTD (183.718 fichas). A coleta respeita o
  robots.txt pela letra e pelo espírito, no ritmo de 1 requisição a cada 3
  segundos por repositório. A fila das instituições autorizadas acabou; a meta
  de 50 mil não foi atingida, como a conta prévia indicava (~26 mil).
- **Corpus tratado:** todos os PDFs coletados foram tratados (25.237 com texto
  extraído). Resultou em 21.515 documentos de 67 instituições, com 461,9
  milhões de palavras e 35.891 dados pessoais mascarados.
- **Produtos:** pré-treino com 21.515 documentos, 3.689 pares de fine-tuning,
  1.000.330 trechos para RAG e 775 itens de benchmark. A verificação final de
  dados pessoais encontrou 0 ocorrências.
- **Qualidade:** 164 testes automáticos e 24 defeitos corrigidos, a maioria
  achada por leitura manual dos dados.
- **Limites:** o corpus é o que cabe no protocolo de coleta. A busca por outras
  fontes além da BDTD não abriu caminho (seção 8).

## 1. Enunciado e onde está no código

| Item pedido | Implementação | Código |
|---|---|---|
| Crawler da BDTD para Saúde | inventário por OAI-PMH e pelo inventário da BDTD; página do item até o PDF; download por instituição | `src/raw/` |
| Arquitetura em camadas | Raw → Staging → Processed → Curated; nenhuma camada altera a anterior | `src/`, `run_pipeline.py` |
| Tratamento na Processed | extração com OCR, normalização, padronização, anonimização, qualidade, escopo e deduplicação | `src/processed/` |
| Produtos na Curated | pré-treino, fine-tuning, RAG, benchmarks e verificação de dados pessoais | `src/curated/` |

As decisões de projeto (fontes, filtros, ritmo, limiares) ficam em
`config/config.yaml`. Cada camada grava um relatório com entradas, saídas,
métricas e falhas em `data/reports/saude/`.

## 2. Arquitetura

```
FONTES     OAI-PMH da UFMG  +  inventário da BDTD
  │
  ├─ RAW        metadado cru e PDF original, sem alteração
  ├─ STAGING    tabelas Parquet, codificação corrigida, tipo real do arquivo
  ├─ PROCESSED  extração, limpeza, padronização, anonimização, filtros, dedup
  └─ CURATED    pré-treino, fine-tuning, RAG, benchmarks, verificação de PII
```

Nenhuma camada modifica a anterior. Por isso, corrigir um filtro exige apenas
reprocessar a partir da camada afetada, sem baixar nada de novo.

```bash
python -m pytest                        # testes
python preflight.py                     # verificação antes de coletar
python -m src.raw.inventario robots     # evidência de robots.txt por domínio
python -m src.raw.inventario bdtd_csv   # candidatos do inventário da BDTD
python run_pipeline.py --camadas raw    # download
python run_pipeline.py --camadas staging processed curated
```

## 3. Coleta (Raw)

### 3.1 Fontes

A BDTD guarda as fichas dos trabalhos, mas o PDF fica no repositório de cada
universidade. Por isso a coleta tem dois passos: montar a lista de trabalhos e,
para cada um, achar o PDF no repositório de origem.

- **OAI-PMH da UFMG** (conjunto de Ciências da Saúde). A colheita é fatiada em
  janelas de datas, porque a paginação profunda do servidor falha. Uma janela
  que falha é dividida ao meio; se não se recuperar, a perda é declarada.
- **Inventário da BDTD**, montado pelo grupo pela API da BDTD (183.718 fichas).
  A busca da interface, proibida a robôs, não é usada. A API tem limites que
  exigiram fatiar a consulta: a paginação para na página 10 e as facetas
  devolvem no máximo 30 valores. Sobre o inventário aplicam-se os filtros do
  projeto: acesso aberto; escopo de Saúde por radicais ("odontolog" pega
  "odontológico"); e exclusão de zootecnia e veterinária por palavra inteira.
  Na coleta final não há limite por instituição: 58.491 candidatos no escopo.

### 3.2 Da página do item ao PDF

O coletor tenta, nesta ordem:

1. a metatag `citation_pdf_url`;
2. os links de arquivo da página;
3. o visualizador embutido em `<object type="application/pdf">`, usado pelo
   SidUece da UECE;
4. no Tainacan (UNB), o campo `uri-handle` do item, lido pela API do próprio
   Tainacan, que aponta para o DSpace antigo onde o PDF está;
5. nos repositórios DSpace 7 que entregam a página sem links, a API REST do
   próprio repositório, com o endereço lido de `assets/config.json`.

O coletor também corrige endereços internos publicados por engano, como
`localhost` ou IP com porta 4000. Só grava arquivos que começam com `%PDF` e
têm até 120 MB. O download é retomável: um PDF que já está no disco não gera
nova requisição.

### 3.3 Conduta de rede

| Regra | Implementação |
|---|---|
| Identificação | User-Agent com projeto, instituição e e-mail de contato |
| Ritmo | 1 requisição a cada 3 s por repositório, ou o Crawl-delay, se maior; até 24 instituições em paralelo, sem acelerar nenhum domínio |
| robots.txt | respeitado em todos os caminhos de rede e em cada redirecionamento |
| Letra e espírito | fica fora o domínio que veta robôs de IA pelo nome, que responde com desafio anti-robô (inclusive o da plataforma Sophia, na UNICAMP) ou que bloqueia o nosso agente. A checagem é feita antes da coleta e, nos links de handle, no domínio final |
| Critérios de parada | disjuntor por instituição (erro acima de 30% após 20 tentativas, ou 20 falhas de rede seguidas); na colheita OAI, 5 falhas seguidas |
| Antes de coletar | testes e preflight, que bloqueiam a coleta sem evidência de robots.txt por domínio ou com ritmo acima do protocolo |
| TLS | verificação de certificado nunca desligada |

## 4. Staging

A Staging converte o JSONL cru em quatro tabelas Parquet (documentos, autores,
assuntos e arquivos), corrige a codificação, confere o tipo real de cada arquivo
pelos primeiros bytes e valida a integridade. Nada é descartado nessa camada.
Na última execução, foram 38.134 fichas, 25.324 delas com arquivo, de 95
instituições; os 14 arquivos sem ficha atual foram apenas registrados.

## 5. Tratamento (Processed)

As etapas seguem esta ordem: extração → normalização → anonimização →
qualidade → escopo → deduplicação. A ordem importa: filtrar antes de normalizar
reprova documento com codificação quebrada, e anonimizar antes de normalizar
faz o detector de CPF errar.

- **Extração:** PyMuPDF, com OCR (Tesseract, português) quando a maioria das
  páginas é imagem.
- **Normalização:** codificação (`ftfy`), Unicode NFC, ligaduras, cabeçalhos e
  rodapés repetidos, números de página e hifenização. Também corta tudo antes
  do RESUMO e os anexos.
- **Padronização:** idioma em código ISO, tipo como "dissertação de mestrado" ou
  "tese de doutorado" e ano como inteiro, com o valor original preservado.
- **Anonimização** de dados de terceiros no texto, no título e no resumo. Autor
  e orientador não são mascarados, porque são dado bibliográfico público.

| Detector | Regra |
|---|---|
| E-mail e perfil de rede social | padrão textual |
| CPF, CNPJ, título de eleitor, PIS/PASEP e cartão SUS | só com dígito verificador válido |
| Telefone | DDD válido, fixo começando de 2 a 5, celular com 9; intervalo de anos recusado |
| CEP e RG | formato; RG com 7 a 10 dígitos |
| Links, DOI e ORCID | protegidos dos detectores numéricos |

Cada máscara é registrada com o trecho em volta já mascarado. A precisão foi
medida recuperando o valor por trás de cada máscara: ~1.900 eram falsas (DOI e
ORCID tomados por documento, nome de gene tomado por placa) e foram eliminadas.

- **Qualidade:** heurísticas no estilo Gopher/RefinedWeb, calibradas para tese
  em português: proporção de texto, símbolos, stopwords, linhas repetidas e
  idioma.
- **Escopo:** exclusão de zootecnia e veterinária por palavra inteira, com uma
  lista de expressões permitidas, como "pé equino" e "soro fetal bovino".
- **Deduplicação:** exata (SHA-256) e aproximada (MinHash com LSH, Jaccard a
  partir de 0,80).

## 6. Produtos (Curated)

| Produto | Formato | Uso |
|---|---|---|
| Pré-treino | JSONL com id, texto e metadados | pré-treino continuado de modelo existente |
| Fine-tuning | JSONL com mensagens e metadados | seguir instruções |
| RAG | Parquet, trechos de 500 palavras com metadados | busca com citação da fonte |
| Benchmark | recuperação, múltipla escolha e perplexidade | avaliação |

- Treino, validação e teste são divididos por autor e programa, e o treino é
  descontaminado contra a avaliação.
- Os pares de fine-tuning saem de campos do próprio documento (título, resumo,
  palavras-chave e introdução), sem texto gerado por modelo. Texto em inglês não
  entra.
- A **verificação final de dados pessoais** varre todos os produtos e interrompe
  o pipeline com erro se encontrar qualquer ocorrência.
- Os benchmarks medem recuperação sobre o acervo, não conhecimento de Saúde.

## 7. Verificação de qualidade

O projeto tem **164 testes automáticos** (`python -m pytest`), que não acessam a
rede nem os dados reais. Cada defeito corrigido ganhou um teste com o caso real
que o revelou. A cada reprocessamento, o grupo leu textos tratados, pares de
fine-tuning e amostras das máscaras de dados pessoais. No total, 24 defeitos
foram corrigidos; os principais estão abaixo.

| Área | Defeito | Correção |
|---|---|---|
| Escopo | teses de zootecnia no corpus e, no sentido oposto, 10 teses de Saúde excluídas por "saneamento" ou "pé equino" | exclusão por palavra inteira, com todas as flexões e expressões permitidas |
| Anonimização | ~1.900 máscaras falsas sobre DOI, ORCID e nomes de gene | dígito verificador e proteção de links |
| Anonimização | telefone real quebrado em linha escapava; foi achado porque a verificação final parou o pipeline | quebra de linha aceita depois do DDD |
| Fine-tuning | resposta copiada na pergunta (186 pares) e, depois, abstract em inglês no lugar do trecho (109 pares) | trecho tirado da introdução e trava de idioma |
| Direitos | 16 documentos de acesso restrito quase entraram no corpus | filtro de acesso aberto em todos os caminhos |
| Coleta | repositórios DSpace 7 sem PDF localizável e endereços internos publicados | API REST com endereço do config.json e troca do endereço interno |
| Coleta | UNB (Tainacan) e UECE (SidUece) sem PDF localizável; página de desafio da UNICAMP contada como "PDF não localizado" | salto pelo `uri-handle` do Tainacan, leitura do `<object>` embutido e detecção do desafio anti-robô |
| Coleta | paralelismo travava num mesmo domínio; o disjuntor cortava instituições boas ao retomar | paralelismo por instituição e disjuntor com histórico |
| Processamento | o RAG estourava a memória; texto de rodada anterior era reaprovado | gravação em lotes e Processed restrita ao Staging atual |

## 8. Incidentes e perdas

| Evento | O que houve | Decisão |
|---|---|---|
| Janela de datas da UFMG (fevereiro a junho de 2026) | o servidor responde HTTP 500; dos 755 registros, 235 foram recuperados | ~520 registros declarados como perdidos |
| Piloto do inventário (UFRN, UFPR, Fiocruz) | 0 de 180 PDFs, por variações de DSpace 7 e pelo servidor de handles da UFPR fora do ar | coletor corrigido (119 de 120 na repetição); UFPR fora |
| robots.txt de 76 domínios do inventário | 23.993 dos 58.491 candidatos ficam fora: inacessibilidade (11.154), HTTP 403, 468 ou 5xx (8.193), veto a robôs de IA (4.413), bloqueio total (187) e desafio anti-robô (46) | 34.498 candidatos autorizados |
| Disjuntor na coleta em escala | 26 instituições cortadas na primeira execução | 7 defeitos do coletor corrigidos; instituições com falha confirmada (certificado inválido, handle fora do ar, desafio anti-robô, links quebrados) suspensas sem nenhuma requisição (23 hoje) |
| Fiocruz (14/09) | o repositório parou de responder depois de 18 downloads; 376 falhas seguidas até o corte | suspensa; o disjuntor passou a cortar também por 20 falhas de rede seguidas |
| Reverificação das suspensas (16/09) | UNB corrigida (861 de 870 PDFs); UECE tem só 8 de 20, porque boa parte dos registros não tem arquivo digital; UNICAMP responde com desafio anti-robô por token; UFRRJ devolve HTTP 403 de forma intermitente | UNB reabilitada; UECE, UNICAMP e UFRRJ seguem suspensas |
| Outras fontes | o robots.txt do Oasisbr veta pelo nome ClaudeBot e outros robôs de IA; o Catálogo de Teses da CAPES cobre só 2021–2024, sem link para o PDF | Oasisbr descartado pelo critério da letra e do espírito; CAPES sem uso |
| Fim da fila | a fila das instituições autorizadas esgotou em 24.443 PDFs (15/09); meta de 50 mil não atingida | coleta encerrada em 25.338 PDFs |

## 9. Resultados

### 9.1 Coleta

| Etapa | PDFs |
|---|---:|
| UFMG pelo OAI-PMH | 3.477 |
| Piloto do inventário e coleta até 15 mil | 11.621 |
| Coleta até 50 mil pelo inventário (fila esgotada) | 9.345 |
| Reabilitação de instituições (UNB 881, UECE 8) | 889 |
| Retentativas do Raw final | 6 |
| **Total** | **25.338** |

Os PDFs vêm de 67 instituições. Além da UFMG, as que mais contribuíram foram
UFRN (3.483), UFG (1.665), UFSCar (1.598), UFU (1.461), UEM (1.274), UNESP
(1.242), UFS (1.052), UFES (1.036), UFMA (953), UEL (891) e UNB (881).

### 9.2 Corpus tratado

Todos os PDFs coletados passaram pela Processed, sem amostra (a opção
`processed.amostra` do `config.yaml` ficou em 0).

| Métrica | Valor |
|---|---|
| PDFs tratados | 25.237 (87 sem texto: 75 com falha de leitura do PDF e 12 sem texto suficiente) |
| Documentos no corpus | 21.515 de 67 instituições: UFMG 2.845 e 18.670 das demais |
| Aprovação | 82% na UFMG e 86% nas demais instituições |
| Palavras | 461,9 milhões (mediana de 17.681 por documento) e 2,25 milhões de páginas |
| Período | 1903 a 2026 |
| Reprovados | 3.722 (um documento pode ter mais de um motivo): texto em inglês 2.258, linhas repetitivas 960, fora de escopo 360, pouco texto alfabético 256, curto demais 93, duplicatas 97 |
| Dados pessoais mascarados | 35.891: e-mail 19.859, CEP 9.279, telefone 5.861, outros 892 |

### 9.3 Produtos

| Produto | Treino | Validação | Teste | Total |
|---|---:|---:|---:|---:|
| Pré-treino (documentos) | 19.361 | 1.084 | 1.070 | 21.515 |
| Fine-tuning (pares) | 3.361 | 192 | 136 | 3.689 |
| RAG (trechos) | — | — | — | 1.000.330 |
| Benchmark (itens) | — | — | — | 775 |

A verificação final de dados pessoais encontrou 0 ocorrências nos 14 arquivos
de produtos. A descontaminação não achou nenhum documento de treino parecido com
os de avaliação.

## 10. Limitações

- O corpus tem o tamanho que o protocolo permite: a fila das instituições
  autorizadas acabou em ~25 mil PDFs. Crescer exigiria fontes fora da BDTD ou a
  reabilitação de instituições suspensas, e as duas frentes testadas esbarraram
  em veto explícito a robôs de IA (Oasisbr) ou em cobertura curta (CAPES).
- A UFRN (3.024 documentos) e a UFMG (2.845) somam 27% do corpus. A cobertura
  é desigual: há instituições fora por robots.txt, por falhas de servidor, por
  desafio anti-robô ou por sistemas que o coletor não reconhece.
- Nos documentos do inventário, que não têm resumo, o escopo é checado pelo
  começo do texto. Na amostra examinada em 13/09, cerca de 7 das 18 exclusões
  desses documentos eram de Saúde. Por exemplo, o sobrenome "Bezerra" casou com
  o termo de exclusão "bezerra", e "recursos hídricos" apareceu num estudo sobre
  dengue e clima. A regra não foi refinada e as 360 exclusões por escopo do
  corpus atual não foram revisadas uma a uma.
- O filtro por radicais também admite trabalhos de gestão e economia da saúde,
  como estudos sobre operadoras de planos de saúde.
- Os documentos do inventário chegam sem resumo, o que reduz os pares de
  fine-tuning.
- O recall da anonimização não foi medido, e quase-identificadores (idade,
  doença rara, município) não são tratados. Por isso o corpus não é declarado
  anonimizado.
- O fine-tuning por template de metadados e os benchmarks de recuperação não
  medem conhecimento de Saúde.
- Acesso aberto não é licença de redistribuição: os dados não são publicados
  nem entregues.
