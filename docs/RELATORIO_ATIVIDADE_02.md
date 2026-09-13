# Relatório — Atividade 02: pipeline de dados de teses e dissertações de Saúde

**Grupo 7:** Eduardo Melo, Otávio França e Ygor Morais  
**Disciplina:** Tópicos em Inteligência Artificial (DC/CCN072) — UFPI — Prof. Raimundo Santos Moura  
**Data:** 13/09/2026  
**Código:** repositório `bdtd-corpus`. O protocolo de coleta completo está em `docs/PROTOCOLO_DE_COLETA.md`.

## Resumo

O grupo construiu um pipeline em quatro camadas (Raw → Staging → Processed →
Curated). Ele coleta teses e dissertações de Saúde e as transforma em dados
para pré-treino continuado, fine-tuning, RAG e avaliação de modelos de
linguagem em português.

- **Coleta:** 15.098 PDFs de acesso aberto, de 62 instituições, pelo OAI-PMH da
  UFMG e pelo inventário da BDTD (183.718 fichas). A coleta respeita o
  robots.txt pela letra e pelo espírito, no ritmo de 1 requisição a cada 3
  segundos por repositório.
- **Corpus tratado:** 2.951 documentos (72,0 milhões de palavras), a partir dos
  primeiros 3.596 PDFs, com 4.937 dados pessoais mascarados.
- **Produtos:** pré-treino com 2.951 documentos, 978 pares de fine-tuning,
  155.312 trechos para RAG e 784 itens de benchmark. A verificação final de
  dados pessoais encontrou 0 ocorrências.
- **Qualidade:** 156 testes automáticos e 21 defeitos corrigidos, a maioria
  achada por leitura manual dos dados.
- **Limites:** a coleta parou em 15.098 PDFs pelo prazo; a meta era 20 mil. Os
  PDFs coletados além dos primeiros 3.596 ainda não passaram pelo tratamento.

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
  "odontológico"); exclusão de zootecnia e veterinária por palavra inteira; e
  até 800 candidatos sorteados por instituição.

### 3.2 Da página do item ao PDF

O coletor tenta, nesta ordem:

1. a metatag `citation_pdf_url`;
2. os links de arquivo da página;
3. nos repositórios DSpace 7 que entregam a página sem links, a API REST do
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
| Letra e espírito | fica fora o domínio que veta robôs de IA pelo nome, que responde com desafio anti-robô ou que bloqueia o nosso agente. A checagem é feita antes da coleta e, nos links de handle, no domínio final |
| Critérios de parada | disjuntor por instituição (erro acima de 30% após 20 tentativas); na colheita OAI, 5 falhas seguidas |
| Antes de coletar | testes e preflight, que bloqueiam a coleta sem evidência de robots.txt por domínio ou com ritmo acima do protocolo |
| TLS | verificação de certificado nunca desligada |

## 4. Staging

A Staging converte o JSONL cru em quatro tabelas Parquet (documentos, autores,
assuntos e arquivos), corrige a codificação, confere o tipo real de cada arquivo
pelos primeiros bytes e valida a integridade. Nada é descartado nessa camada.

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

O projeto tem **156 testes automáticos** (`python -m pytest`), que não acessam a
rede nem os dados reais. Cada defeito corrigido ganhou um teste com o caso real
que o revelou. A cada reprocessamento, o grupo leu textos tratados, pares de
fine-tuning e amostras das máscaras de dados pessoais. No total, 21 defeitos
foram corrigidos; os principais estão abaixo.

| Área | Defeito | Correção |
|---|---|---|
| Escopo | teses de zootecnia no corpus e, no sentido oposto, 10 teses de Saúde excluídas por "saneamento" ou "pé equino" | exclusão por palavra inteira, com todas as flexões e expressões permitidas |
| Anonimização | ~1.900 máscaras falsas sobre DOI, ORCID e nomes de gene | dígito verificador e proteção de links |
| Anonimização | telefone real quebrado em linha escapava; foi achado porque a verificação final parou o pipeline | quebra de linha aceita depois do DDD |
| Fine-tuning | resposta copiada na pergunta (186 pares) e, depois, abstract em inglês no lugar do trecho (109 pares) | trecho tirado da introdução e trava de idioma |
| Direitos | 16 documentos de acesso restrito quase entraram no corpus | filtro de acesso aberto em todos os caminhos |
| Coleta | repositórios DSpace 7 sem PDF localizável e endereços internos publicados | API REST com endereço do config.json e troca do endereço interno |
| Coleta | paralelismo travava num mesmo domínio; o disjuntor cortava instituições boas ao retomar | paralelismo por instituição e disjuntor com histórico |
| Processamento | o RAG estourava a memória; texto de rodada anterior era reaprovado | gravação em lotes e Processed restrita ao Staging atual |

## 8. Incidentes e perdas

| Evento | O que houve | Decisão |
|---|---|---|
| Janela de datas da UFMG (fevereiro a junho de 2026) | o servidor responde HTTP 500; dos 755 registros, 235 foram recuperados | ~520 registros declarados como perdidos |
| Piloto do inventário (UFRN, UFPR, Fiocruz) | 0 de 180 PDFs, por variações de DSpace 7 e pelo servidor de handles da UFPR fora do ar | coletor corrigido (119 de 120 na repetição); UFPR fora |
| robots.txt de 179 domínios | 21.253 de 35.238 candidatos autorizados | saíram por inacessibilidade (6.495), HTTP 403, 468 ou 5xx (4.616), veto a robôs de IA (2.641), bloqueio total (187) e desafio anti-robô (46) |
| Disjuntor na coleta em escala | 26 instituições cortadas na primeira execução | 7 defeitos do coletor corrigidos; 23 instituições com falha confirmada (certificado inválido, handle fora do ar, desafio anti-robô, links quebrados) suspensas sem nenhuma requisição |
| Prazo de entrega | meta de 20 mil PDFs | coleta parada em 15.098 PDFs |

## 9. Resultados

### 9.1 Coleta

| Etapa | PDFs |
|---|---:|
| UFMG pelo OAI-PMH | 3.477 |
| Piloto do inventário (UFRN e Fiocruz) | 119 |
| Coleta em escala pelo inventário | 11.502 |
| **Total** | **15.098** |

Os PDFs vêm de 62 instituições. Além da UFMG, as que mais contribuíram foram
Fiocruz (842), UFS e UNESP (800 cada), UFU (797), UFG (704), UFSCar (702),
UFV (700) e UFRN (697).

### 9.2 Corpus tratado (primeiros 3.596 PDFs)

| Métrica | Valor |
|---|---|
| Documentos no corpus | 2.951 (UFMG 2.845, Fiocruz 54, UFRN 52) |
| Palavras | 72,0 milhões (mediana de 20.546 por documento) |
| Reprovados | 631: texto em inglês 445, linhas repetitivas 150, pouco texto 42, fora de escopo 32, duplicatas 3 |
| Dados pessoais mascarados | 4.937: e-mail 2.992, CEP 1.244, telefone 626, outros 75 |

### 9.3 Produtos

| Produto | Treino | Validação | Teste | Total |
|---|---:|---:|---:|---:|
| Pré-treino (documentos) | 2.652 | 150 | 149 | 2.951 |
| Fine-tuning (pares) | 882 | 55 | 41 | 978 |
| RAG (trechos) | — | — | — | 155.312 |
| Benchmark (itens) | — | — | — | 784 |

A verificação final de dados pessoais encontrou 0 ocorrências nos 11 arquivos
de produtos.

## 10. Limitações

- A coleta parou em 15.098 PDFs pelo prazo. O tratamento e os produtos
  correspondem aos primeiros 3.596 PDFs; os demais estão coletados e podem ser
  reprocessados sem nova requisição.
- A cobertura é desigual: há instituições fora por robots.txt, por falhas de
  servidor ou por sistemas que o coletor não reconhece (Tainacan, JSF).
- Os documentos do inventário chegam sem resumo, o que reduz os pares de
  fine-tuning.
- O recall da anonimização não foi medido, e quase-identificadores (idade,
  doença rara, município) não são tratados. Por isso o corpus não é declarado
  anonimizado.
- O fine-tuning por template de metadados e os benchmarks de recuperação não
  medem conhecimento de Saúde.
- Acesso aberto não é licença de redistribuição: os dados não são publicados
  nem entregues.
