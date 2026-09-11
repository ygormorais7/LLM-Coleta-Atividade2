# Atividade 02 — Preparação de Dados

**Disciplina:** DC/CCN072 — UFPI
**Área escolhida:** Saúde
**Autor:** Ygor Morais — ygor.morais@ufpi.edu.br
**Data:** 11 de setembro de 2026
**Fonte:** BDTD/IBICT — OAI-PMH, Repositório Institucional da UFMG

## Resumo

Este relatório documenta a construção de um corpus de teses e dissertações
da área de Saúde a partir da Biblioteca Digital Brasileira de Teses e
Dissertações (BDTD), organizado em arquitetura de quatro camadas. Da
colheita de 2.000 registros de metadado e 508 PDFs baixados, o pipeline de
tratamento produziu um corpus final de **386 documentos** (**9.027.969
palavras**) e os quatro produtos exigidos para consumo por LLM: pré-treino
continuado, fine-tuning (SFT), RAG e benchmarks de avaliação.

| | |
|---|---|
| PDFs baixados | 508 |
| Documentos no corpus final | 386 |
| Palavras totais | 9,03M |
| Chunks de RAG | 19.439 |
| Defeitos achados só por leitura manual | 2 |

## Objetivo

A atividade pede quatro entregas: (1) um crawler para a BDTD; (2)
organização em arquitetura multi-camada (Raw, Staging, Processed, Curated);
(3) um pipeline de tratamento na camada Processed (padronização,
normalização, deduplicação e anonimização); e (4) geração, na camada
Curated, de dados para pré-treino continuado, fine-tuning, RAG e
benchmarks. Este relatório segue essa mesma ordem, com os números e as
decisões de projeto de cada etapa.

## Arquitetura em quatro camadas

Cada camada lê apenas o que a anterior gravou em disco e escreve artefatos
novos — nunca modifica a camada de onde leu. Essa separação é o que
permite, por exemplo, corrigir um filtro de qualidade e reprocessar só a
partir da Processed, sem recolher PDF nenhum de novo.

```
RAW  ──508 pdfs de 2.000 registros──▶  STAGING  ──508 arquivos validados──▶  PROCESSED  ──386 aprovados (qualidade + escopo + direitos)──▶  CURATED
```

Cada seta é uma camada de filtragem: nenhum documento reprovado é
descartado do disco, só marcado como fora do corpus final.

## 1 · Raw — coleta

A coleta usa o protocolo **OAI-PMH** diretamente sobre o repositório
institucional de origem — não a API de busca da BDTD — com
`metadata_prefix=dim` sobre o conjunto `com_1843_6` do Repositório
Institucional da UFMG. A amostragem é por **cota estratificada por ano de
defesa** (2015–2019, 2020–2024, 2025–2029), não por ordem de chegada do
*harvest*, para não enviesar o corpus para os anos mais recentes.

### Coleta responsável

- `Crawl-delay` do `robots.txt` é respeitado em **todos** os caminhos de
  rede, não só no download do PDF — inclusive na própria colheita de
  metadado OAI.
- A UNIFESP foi suspensa da coleta nesta rodada por violar
  `Crawl-delay: 15` em uma versão anterior do harvester.
- `preflight.py` é obrigatório antes de qualquer coleta; a execução para
  se houver bloqueio.
- Verificação de TLS sempre ativa; taxa de requisição é fixa no
  `config.yaml` e nunca foi aumentada para acelerar uma coleta lenta.

**Resultado da coleta — 2026-09-11**

| Métrica | Valor |
|---|---:|
| Registros de metadado colhidos | 2.000 |
| PDFs baixados | 508 |
| Volume transferido | 1,8 GB |
| Taxa de resolução global | 97,7% |
| Duração da coleta | 53 min |

**Cota por estrato (ano de defesa)**

| Estrato | Cota | Obtidos | Taxa |
|---|---:|---:|---:|
| 2015–2019 | 280 | 280 | 100,0% |
| 2020–2024 | 175 | 181 | 98,4% |
| 2025–2029 | 45 | 47 | 83,9% |

Das 508 tentativas de download, 12 falharam: 9 porque a URL retornou
conteúdo que não era PDF e 3 porque o PDF não foi localizado no registro de
origem.

> **Pendência conhecida.** A janela de datestamp `2026-02-25..2026-06-25`
> falhou com HTTP 500 persistente durante a colheita de metadado e foi
> pulada sem retry. O número de registros de Saúde perdidos nessa janela é
> desconhecido — não está refletido nos 2.000 registros colhidos acima.

## 2 · Staging — organização

Converte o JSONL cru em quatro tabelas Parquet tipadas (`documentos`,
`autores`, `assuntos`, `arquivos`) e valida integridade referencial antes
de liberar a camada seguinte.

| Tabela | Linhas |
|---|---:|
| documentos | 2.000 |
| autores | 2.000 |
| assuntos | 11.367 |
| arquivos (com PDF) | 508 |

Validação de integridade — arquivos órfãos, arquivos ausentes, chave
estrangeira quebrada com autores/assuntos, título ausente ou duplicado —
fechou em **zero falhas**. Período coberto pelos registros: 2019–2026, de
uma única instituição (UFMG) nesta rodada.

## 3 · Processed — tratamento de dados

A camada mais cara do pipeline, em três blocos aplicados nesta ordem
obrigatória — inverter a ordem quebra os dois blocos seguintes: filtrar
antes de normalizar reprova documento bom por mojibake; anonimizar antes de
normalizar faz o regex de CPF errar por causa de hifenização e espaço
Unicode.

### Padronização e normalização

Correção de encoding e mojibake (`ftfy`), normalização Unicode NFC,
ligaduras tipográficas; remoção de caracteres de controle e variantes de
espaço Unicode; remoção de cabeçalho e rodapé que se repetem entre páginas;
números de página soltos; hifenização de quebra de linha; pontos de
preenchimento de sumário; colapso de espaços em branco. Corte estrutural do
material pré-textual (capa, ficha catalográfica, folha de aprovação,
agradecimentos) e, quando detectável, do material após referências/anexos
— em tese de Saúde é ali que ficam TCLE, instrumento preenchido e descrição
de caso, a seção de maior risco de PII.

### Anonimização

Remoção de PII de **terceiros** no corpo do texto — CPF e CNPJ com
validação de dígito verificador (para não destruir número de tabela ou
processo que só parece documento), e-mail, telefone, CEP, RG, cartão SUS,
título de eleitor, PIS/PASEP, placa e URL de perfil social. Autor e
orientador não são anonimizados: são dado bibliográfico público, parte da
citação, e removê-los destruiria a proveniência do corpus. Nesta rodada,
**1.469 ocorrências** de PII foram mascaradas.

### Filtros de qualidade e deduplicação

Heurísticas no espírito Gopher/RefinedWeb calibradas para tese em
português: proporção mínima de texto alfabético, excesso de símbolos,
tamanho médio de palavra fora da faixa, proporção de tokens curtos
(assinatura de tabela mal escaneada), linhas duplicadas, linhas curtas
demais, e detecção de idioma por votação em três janelas retiradas do meio
do documento — amostrar só o começo reprova tese boa, porque o resumo em
português e o abstract em inglês nas primeiras páginas derrubam a confiança
dos dois. Deduplicação exata por SHA-256 do texto normalizado, aproximada
por MinHash+LSH (Jaccard ≥ 0,80) e interna (parágrafo repetido no mesmo
documento).

**Funil desta execução**

| Etapa | Documentos |
|---|---:|
| PDFs com arquivo, extraídos | 508 |
| Reprovados por qualidade (idioma, ruído de OCR, texto insuficiente) | −92 |
| Reprovados por escopo de área e por direitos de acesso | −30 |
| Duplicatas removidas (exata + aproximada) | 0 |
| **Aprovados no corpus final** | **386** |

Nenhum documento de OCR entrou nesta rodada — os 508 PDFs tinham camada de
texto nativa, extraída via `pymupdf`, então o filtro de fragmentação de OCR
não precisou descartar nada por esse motivo.

Métrica boa não é prova disso ter sido feito direito. Dois defeitos só
apareceram lendo o corpus manualmente, não em nenhuma métrica agregada:

> **Achado 1 — leitura manual: contaminação de escopo (zootecnia dentro do
> corpus de Saúde).**
> O filtro de assunto (`nutricao`) casava com "nutrição animal", e a lista
> de exclusão só checava área, título e programa — não o resumo. 14
> documentos de zootecnia/produção animal passaram pelo filtro. Corrigido:
> a exclusão agora também verifica o resumo, e a lista de exclusão da UFMG
> ficou mais específica.
>
> *Evidência de verificação nesta rodada:* um documento sobre resíduo de
> bananicultura em dieta de cordeiros, amostrado manualmente na pasta de
> texto processado, foi corretamente reprovado com motivo
> `fora_do_escopo_area:bananicultura/cordeiros — zootecnia` e não está no
> corpus final.

> **Achado 2 — leitura manual: violação do filtro de acesso aberto.**
> O filtro `somente_acesso_aberto` só existia no caminho antigo da API de
> busca da BDTD. O caminho OAI-PMH real, usado na coleta por cota, baixava
> o PDF de qualquer `url_binario` presente no registro, direitos declarados
> ou não — 16 documentos de Acesso Restrito quase entraram no corpus
> publicável. Corrigido em `harvest.py`.
>
> *Evidência de verificação nesta rodada:* a distribuição de `direitos` no
> corpus final (tabela abaixo) não contém nenhuma entrada de Acesso
> Restrito.

## 4 · Curated — produtos finais

A camada Curated não trata mais o dado — trata o **consumidor**. O mesmo
corpus de 386 documentos aprovados gera quatro produtos em formatos
incompatíveis entre si, porque quatro aplicações diferentes precisam de
coisas diferentes.

**Produtos gerados — 386 documentos de entrada**

| Produto | Conteúdo | Treino | Val. | Teste |
|---|---|---:|---:|---:|
| Pré-treino | documento inteiro, campo `text` | 345 | 21 | 20 |
| SFT | pares instrução/resposta | 426 | 28 | 25 |
| RAG | 19.439 chunks de 500 palavras (sobreposição 50), metadado embutido | — | — | — |
| Benchmark | 40 recuperação · 40 múltipla escolha · 41 perplexidade | — | — | — |

### Metodologia do split

O split é feito **por grupo** (autor + programa), não por documento: se o
mesmo orientando tem dissertação e tese, ou o mesmo laboratório produz
trabalhos com metodologia quase idêntica, dividir por documento vazaria
estilo e conteúdo entre treino e teste. Depois do split, o conjunto de
avaliação é usado para **descontaminar** o treino por MinHash — qualquer
documento de treino parecido demais com um de teste é removido do treino,
nunca do teste. Nesta rodada, 0 documentos de treino colidiram com
avaliação.

**Direitos declarados na fonte — corpus final**

| Direitos | Documentos |
|---|---:|
| Acesso Aberto | 308 |
| Acesso Aberto + licença Creative Commons (BY-NC-ND) | 34 |
| Acesso aberto (grafia alternativa da fonte) | 16 |
| Acesso Aberto + licença Creative Commons (BY-ND) | 12 |
| Outras variantes de licença Creative Commons | 16 |
| **Acesso Restrito** | **0** |

## Limitações conhecidas

- **SFT é gerado por template de metadado** (título, palavras-chave,
  resumo), não é pergunta-e-resposta real sobre o corpo do texto. Serve
  para ensinar formato de instrução, não para memorização de conteúdo
  profundo — se o uso final exigir QA de conteúdo, é o próximo passo, ainda
  não feito.
- **Anonimização é baseada em padrão**, não em NER: nome de paciente
  descrito em prosa num relato de caso clínico não é capturado pelos
  detectores de CPF/e-mail/telefone. Recomenda-se auditoria manual
  amostral antes de publicar.
- **Cobertura de uma única instituição** (UFMG) nesta rodada — o corpus não
  representa a diversidade regional da produção em Saúde no Brasil.
- **Benchmarks automáticos medem recuperação e memória factual**, não
  compreensão de domínio. Um benchmark de domínio exigiria perguntas
  escritas e revisadas por humano.
- **Janela de coleta perdida** (2026-02-25 a 2026-06-25, HTTP 500) — volume
  de registros de Saúde não capturado nessa janela é desconhecido.

## Reprodutibilidade

Todos os números deste relatório vêm dos relatórios por camada, gerados
automaticamente a cada execução e auditáveis sem reprocessar nada:

- `data/reports/saude/raw.json`, `staging.json`, `processed.json`,
  `curated.json` — entradas, saídas e falhas por etapa.
- `data/curated/saude/DATACARD.md` — ficha de dados do corpus final,
  composição e limitações.
- `config/config.yaml` — parâmetros efetivos desta execução (cotas,
  limiares de qualidade, estratégia de anonimização).

---
Corpus BDTD Saúde — Atividade 02, DC/CCN072 UFPI — versão 2026-09-11
