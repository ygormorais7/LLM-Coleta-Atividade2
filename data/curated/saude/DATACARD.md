# DATACARD — Corpus BDTD: Saúde

**Versão:** 2026-09-13
**Fontes de onde os documentos vieram:** OAI-PMH repositorio.ufmg.br (2845); inventário BDTD → arca.fiocruz.br (54); inventário BDTD → repositorio.ufrn.br (52)
**Coletado por:** UFPI — contato: ygor.morais@ufpi.edu.br

## 1. Composição

| Métrica | Valor |
|---|---|
| Documentos no corpus final | 2951 |
| Palavras totais | 72,027,249 |
| Palavras por documento (mediana) | 20546 |
| Período coberto | 1993–2026 |
| Instituições distintas | 3 |
| Idioma | português (filtro com limiar de confiança) |

### Divisão

| Split | Documentos |
|---|---|
| treino | 2652 |
| validacao | 150 |
| teste | 149 |

### Principais instituições

| Instituição | Documentos |
|---|---|
| Universidade Federal de Minas Gerais | 2845 |
| FIOCRUZ | 54 |
| UFRN | 52 |

### Direitos declarados na fonte

| Direitos | Documentos |
|---|---|
| Acesso Aberto | 2301 |
| Acesso Aberto; http://creativecommons.org/licenses/by-nc-nd/3.0/pt/ | 271 |
| openAccess | 106 |
| Acesso aberto | 89 |
| Acesso Aberto; http://creativecommons.org/licenses/by-nd/3.0/pt/ | 61 |
| Acesso Aberto; http://creativecommons.org/licenses/by/3.0/pt/ | 21 |
| Acesso aberto; http://creativecommons.org/licenses/by-nc-nd/3.0/pt/ | 20 |
| Acesso Aberto; http://creativecommons.org/licenses/by-nc-sa/3.0/pt/ | 15 |

## 2. Produtos gerados

| Produto | Conteúdo |
|---|---|
| `pretreino/*.jsonl` | {'treino': 2652, 'validacao': 150, 'teste': 149} — documento inteiro, campo `text` |
| `sft/*.jsonl` | {'treino': 882, 'validacao': 55, 'teste': 41} — pares instrução/resposta no formato `messages` |
| `rag/corpus_rag.parquet` | 155312 chunks de 500 palavras (sobreposição 50) |
| `benchmark/` | {'recuperacao': 292, 'multipla_escolha': 292, 'perplexidade': 200} |

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
  SFT e no benchmark. Estratégia: `mascara`.
- **Deduplicação:** exata (SHA-256 do texto normalizado), aproximada
  (MinHash+LSH, Jaccard ≥ 0.8)
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
