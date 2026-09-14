# DATACARD — Corpus BDTD: Saúde

**Versão:** 2026-09-13
**Fontes de onde os documentos vieram:** OAI-PMH repositorio.ufmg.br (2845); inventário BDTD → repositorio.ufrn.br (90); inventário BDTD → arca.fiocruz.br (90); inventário BDTD → repositorio.uepb.edu.br (39); inventário BDTD → repositorio.utfpr.edu.br (39); inventário BDTD → www.repositorio.ufal.br (39); inventário BDTD → repositorio.unesc.net (38); inventário BDTD → tede.unisantos.br (37); inventário BDTD → saberaberto.uneb.br (36); inventário BDTD → bdtd.famerp.br (36); inventário BDTD → tede2.unifenas.br:8080 (36); inventário BDTD → repositorio.bc.ufg.br (35); inventário BDTD → repositorio.uel.br (35); inventário BDTD → hdl.handle.net (35); inventário BDTD → repositorio.ufu.br (35); inventário BDTD → repositorio.upf.br (35); inventário BDTD → tede2.uefs.br:8080 (35); inventário BDTD → repositorio.unilab.edu.br (35); inventário BDTD → repositorio.ufes.br (34); inventário BDTD → ri.ufs.br (34); inventário BDTD → repositorio.ufscar.br (34); inventário BDTD → repositorio.uem.br:8080 (34); inventário BDTD → tede.unioeste.br (34); inventário BDTD → bdtd.unoeste.br:8080 (33); inventário BDTD → repositorio.ufgd.edu.br (30); inventário BDTD → repositorio.ucs.br (29); inventário BDTD → archivum.grupomarista.org.br (28); inventário BDTD → repositorio.uscs.edu.br (25); inventário BDTD → repositorio.ufms.br (24); inventário BDTD → repositorio.baraodemaua.br (24); inventário BDTD → locus.ufv.br (22); inventário BDTD → ri.emescam.br (20); inventário BDTD → tede2.unicap.br:8080 (20); inventário BDTD → tedebc.ufma.br (18); inventário BDTD → tedebc.ufma.br:8080 (17); inventário BDTD → repositorio.unipampa.edu.br (16); inventário BDTD → dspace.unipampa.edu.br (16); inventário BDTD → www.tede2.ufrpe.br:8080 (15); inventário BDTD → bibliotecatede.uninove.br (13); inventário BDTD → repositorio.udesc.br (12); inventário BDTD → ridi.ibict.br (10); inventário BDTD → dspace.unila.edu.br (9); inventário BDTD → dspace.est.edu.br:8080 (9); inventário BDTD → repositorio.uenp.edu.br (9); inventário BDTD → tede.fecap.br:8080 (8); inventário BDTD → bib.pucminas.br (8); inventário BDTD → repositorio.ufpa.br (7); inventário BDTD → repositorio.ifes.edu.br (7); inventário BDTD → accamargo.phlnet.com.br (7); inventário BDTD → dspace.mackenzie.br (6); inventário BDTD → repositorio.cefetmg.br (6); inventário BDTD → www.locus.ufv.br (5); inventário BDTD → repositorio.uema.br (5); inventário BDTD → www.alice.cnptia.embrapa.br (5); inventário BDTD → repositorio.ifpb.edu.br (3); inventário BDTD → repositorio.enap.gov.br (2); inventário BDTD → repositorio.ifal.edu.br (2); inventário BDTD → tede.fecap.br (2); inventário BDTD → repositorio.ital.sp.gov.br (1); inventário BDTD → rigeo.sgb.gov.br (1); inventário BDTD → repositorio.ifro.edu.br (1); inventário BDTD → dspace.ifrs.edu.br (1); inventário BDTD → repositorio.ifam.edu.br (1); inventário BDTD → petrus.cp2.g12.br (1); inventário BDTD → tede2.uepg.br (1)
**Coletado por:** UFPI — contato: ygor.morais@ufpi.edu.br

## 1. Composição

| Métrica | Valor |
|---|---|
| Documentos no corpus final | 4219 |
| Palavras totais | 98,824,024 |
| Palavras por documento (mediana) | 19376 |
| Período coberto | 1993–2026 |
| Instituições distintas | 62 |
| Idioma | português (filtro com limiar de confiança) |

### Divisão

| Split | Documentos |
|---|---|
| treino | 3793 |
| teste | 216 |
| validacao | 210 |

### Principais instituições

| Instituição | Documentos |
|---|---|
| Universidade Federal de Minas Gerais | 2845 |
| UFRN | 90 |
| FIOCRUZ | 90 |
| UEPB | 39 |
| UTFPR | 39 |
| UFAL | 39 |
| UNESC | 38 |
| UNISANTOS | 37 |
| UFSCAR | 36 |
| UNEB | 36 |

### Direitos declarados na fonte

| Direitos | Documentos |
|---|---|
| Acesso Aberto | 2301 |
| openAccess | 1374 |
| Acesso Aberto; http://creativecommons.org/licenses/by-nc-nd/3.0/pt/ | 271 |
| Acesso aberto | 89 |
| Acesso Aberto; http://creativecommons.org/licenses/by-nd/3.0/pt/ | 61 |
| Acesso Aberto; http://creativecommons.org/licenses/by/3.0/pt/ | 21 |
| Acesso aberto; http://creativecommons.org/licenses/by-nc-nd/3.0/pt/ | 20 |
| Acesso Aberto; http://creativecommons.org/licenses/by-nc-sa/3.0/pt/ | 15 |

## 2. Produtos gerados

| Produto | Conteúdo |
|---|---|
| `pretreino/*.jsonl` | {'treino': 3793, 'validacao': 210, 'teste': 216} — documento inteiro, campo `text` |
| `sft/*.jsonl` | {'treino': 1057, 'validacao': 58, 'teste': 50} — pares instrução/resposta no formato `messages` |
| `rag/corpus_rag.parquet` | 213573 chunks de 500 palavras (sobreposição 50) |
| `benchmark/` | {'recuperacao': 276, 'multipla_escolha': 300, 'perplexidade': 200} |

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
