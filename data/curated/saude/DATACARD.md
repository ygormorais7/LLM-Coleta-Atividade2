# DATACARD — Corpus BDTD: Saúde

**Versão:** 2026-09-11
**Fonte:** Biblioteca Digital Brasileira de Teses e Dissertações (BDTD/IBICT)
**Coletado por:** UFPI — contato: ygor.morais@ufpi.edu.br

## 1. Composição

| Métrica | Valor |
|---|---|
| Documentos no corpus final | 386 |
| Palavras totais | 9,027,969 |
| Palavras por documento (mediana) | 19376 |
| Período coberto | 2019–2026 |
| Instituições distintas | 1 |
| Idioma | português (filtro com limiar de confiança) |

### Divisão

| Split | Documentos |
|---|---|
| treino | 345 |
| validacao | 21 |
| teste | 20 |

### Principais instituições

| Instituição | Documentos |
|---|---|
| Universidade Federal de Minas Gerais | 386 |

### Direitos declarados na fonte

| Direitos | Documentos |
|---|---|
| Acesso Aberto | 308 |
| Acesso Aberto; http://creativecommons.org/licenses/by-nc-nd/3.0/pt/ | 34 |
| Acesso aberto | 16 |
| Acesso Aberto; http://creativecommons.org/licenses/by-nd/3.0/pt/ | 12 |
| Acesso aberto; http://creativecommons.org/licenses/by-nc-nd/3.0/pt/ | 4 |
| Acesso aberto; Attribution-NonCommercial-NoDerivs 3.0 Brazil; http://creativecommons.org/licenses/by-nc-nd/3.0/br/ | 3 |
| Acesso Aberto; Atribuição-NãoComercial-SemDerivados 3.0 Portugal; http://creativecommons.org/licenses/by-nc-nd/3.0/pt/ | 1 |
| Acesso Aberto; http://creativecommons.org/licenses/by/3.0/pt/ | 1 |

## 2. Produtos gerados

| Produto | Conteúdo |
|---|---|
| `pretreino/*.jsonl` | {'treino': 345, 'validacao': 21, 'teste': 20} — documento inteiro, campo `text` |
| `sft/*.jsonl` | {'treino': 426, 'validacao': 28, 'teste': 25} — pares instrução/resposta no formato `messages` |
| `rag/corpus_rag.parquet` | 19439 chunks de 500 palavras (sobreposição 50) |
| `benchmark/` | {'recuperacao': 40, 'multipla_escolha': 40, 'perplexidade': 41} |

## 3. Como foi construído

`Raw` (resposta crua da API + PDF original) → `Staging` (tabelas Parquet,
validação de integridade) → `Processed` (extração, normalização,
anonimização, filtros de qualidade, deduplicação) → `Curated` (este dataset).

Parâmetros efetivos em `config/config.yaml`; contagens de entrada, saída e
falha por etapa em `data/reports/`.

## 4. Tratamento aplicado

- **Padronização:** UTF-8/NFC, correção de mojibake (ftfy), ligaduras tipográficas.
- **Normalização:** remoção de caracteres de controle, espaços Unicode, cabeçalho
  e rodapé repetidos entre páginas, números de página, hifenização de quebra de
  linha, entidades HTML, colapso de espaços em branco.
- **Anonimização:** CPF e CNPJ (com validação de dígito verificador, para não
  destruir números legítimos), e-mail, telefone, CEP, RG, cartão SUS, título de
  eleitor, PIS/PASEP, placa e URLs de perfil social. Estratégia:
  `mascara`.
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
- **Viés de cobertura.** O acervo reflete quem deposita no repositório e quem
  o IBICT consegue coletar: instituições grandes e do Sudeste estão
  sobrerrepresentadas, e trabalhos anteriores a ~2005 são raros.
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
