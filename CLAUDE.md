# bdtd-corpus

Corpus de teses e dissertações de Saúde para adaptação de domínio de LLM em
português. Disciplina DC/CCN072 — UFPI.

## Arquitetura

Quatro camadas, cada uma lendo a anterior e escrevendo artefatos novos, nunca
modificando-a: **Raw** (metadado OAI-PMH cru + PDF byte a byte) → **Staging**
(JSONL vira Parquet, encoding acertado, tipo de arquivo validado) →
**Processed** (extração de texto, limpeza, anonimização, dedup — a camada
mais cara) → **Curated** (pretreino/sft/rag/benchmark para consumo final).
Trocar a fonte do inventário ou um filtro de qualidade não exige recoletar —
só reprocessar a partir da camada afetada.

## Estado atual do piloto

Terceira rodada (UFMG, `com_1843_6`, `metadata_prefix=dim`, `n_alvo=5000` —
sem corte de cota, pool inteiro pós-filtro): rodou madrugada de 2026-09-11
para 2026-09-12 dentro de tmux, sobreviveu à suspensão da máquina (não foi
desligamento completo) e terminou sozinha. 3.474 PDFs baixados (3.632
candidatos, 185 bloqueados por `acesso_restrito`, taxa de resolução ~96%).
Números brutos dessa primeira passada (**substituídos pela auditoria
abaixo, não usar**): 2.873 no corpus, ~69,98M palavras.

Auditoria manual do corpus (2026-09-12, ver seção de defeitos): achada
contaminação de escopo e ruído de PII, mais um bug de métrica achado ao
corrigir os outros (páginas/OCR zerando). Reprocessados Processed+Curated
localmente (sem rede) com os 4 consertos — a 1ª passada (sem reextrair
PDF) já corrigiu escopo/PII e deu 2.838 docs; a 2ª passada (reextração
completa, pra repopular `extracao_stats.jsonl`) deu 2.840 — a variação de
±2 entre rodadas de reextração é ruído normal de OCR (Tesseract não é
100% determinístico entre execuções), não uma regressão.

**Estado final da 3ª rodada, pós-auditoria: 2.840 no corpus final, ~69,15M
palavras** (mediana 20.513 palavras/doc). 620 reprovados (618 qualidade +
2 duplicata; 39 desses 618 são por escopo — zootecnia), 2 duplicatas
exatas, 0 fuzzy, 0 vazamento treino/avaliação, 14 arquivos órfãos de
rodada anterior ignorados. RAG: 149.071 chunks. PII removida caiu de
10.141 para 7.961 ocorrências (falsos positivos eliminados). 327.257
páginas totais, 57 documentos com OCR. Ainda 1 IES só (UFMG) — ~183 mil
nacionais exigiria habilitar mais fontes.

(Rodadas anteriores, números antigos, não somar com os atuais: segunda
rodada 508 PDFs / 386 aprovados / ~9,03M palavras; primeira rodada, outras
fontes, 308 PDFs / 273 aprovados / ~7,3M palavras.)

Correções feitas e validadas contra a rede real nesta rodada: `Crawl-delay`
honrado também na colheita OAI (`ClienteOAI._aplicar_crawl_delay`), UNIFESP
suspensa (violava `Crawl-delay: 15`), `janela_dias` para paginação profunda do
DSpace, `programa` extraído via `metadata_prefix=dim` (o campo real é
`mdschema="local" element="publisher" qualifier="program"`, não
`dc.publisher.program` como documentação teórica sugere — só existe quando a
IES preencheu na origem).

Defeitos achados **só lendo o corpus manualmente**, nenhum por métrica
(508 -> 386 documentos):
1. **Contaminação de escopo**: 14 documentos de zootecnia/produção animal
   passaram pelo filtro (`nutricao` no `filtro_assunto` casa com nutrição
   animal; `excluir_assunto` só checava área/título/programa, não o resumo —
   corrigido, agora checa o resumo também, e a lista de exclusão da UFMG
   ficou mais específica).
2. **Violação do `somente_acesso_aberto`**: esse filtro só existia no caminho
   antigo da API da BDTD (`baixar_textos`); o caminho OAI-PMH real
   (`baixar_por_cota`) baixava PDF de qualquer `url_binario`, direitos ou não
   — 16 documentos de Acesso Restrito quase entraram no corpus publicável.
   Corrigido em `harvest.py`.

Mais três achados na auditoria manual da 3ª rodada (2.873 documentos,
2026-09-12), depois de o corpus crescer de 386 para quase 3.000 — de novo,
nenhum por métrica:

3. **Contaminação de escopo voltou, maior**: `excluir_assunto` só tinha o
   plural masculino ("bovinos", "ovinos"...). Nome de doença concorda no
   feminino singular em português ("raiva bovina", "brucelose bovina") —
   não contém a substring do termo excluído e passava direto. Pelo menos 17
   títulos de zootecnia/agropecuária pura no corpus (novilhos Nelore,
   pastagem, biofertilizante suíno...). Corrigido: lista de exclusão ganhou
   as variações de gênero/número e vocabulário de zootecnia
   (`config.yaml`), e a checagem agora roda também em `processed/run.py`
   (`_termos_exclusao_escopo`/`_fora_de_escopo`) — assim um `excluir_assunto`
   mais novo se aplica retroativamente ao que já foi baixado, sem recoletar
   (motivo gravado como `fora_de_escopo_zootecnia`). CUIDADO ao adicionar
   radical curto à lista: `"equin"` sozinho casaria com "catequina" /
   "epigalocatequina" (flavonoide, Saúde legítima) — sempre testar contra o
   corpus antes de adicionar termo novo.
4. **Falso positivo de PII destruindo conteúdo**: os detectores `TELEFONE`,
   `PLACA` e `TITULO_ELEITOR` (sem validador de dígito, ao contrário de
   CPF/CNPJ) eram regex numéricos/alfanuméricos genéricos demais para texto
   técnico. Achados reais: código de procedimento odontológico
   `0101020058` mascarado como `[TELEFONE]` 219 vezes num documento; nome de
   composto químico `PEG6000` mascarado como `[PLACA]` 136 vezes; eixo de
   anos num gráfico ("1991 1992 1993") mascarado como `[TITULO_ELEITOR]`.
   Corrigido em `processed/clean.py`: separador agora obrigatório (não mais
   opcional) entre os blocos de dígito, e `PLACA` exige hífen (formato
   antigo) ou letra na 5ª posição (Mercosul) em vez de aceitar dígito ali.
   PII removida no corpus caiu de 10.141 para 7.953 ocorrências.
5. **Processed reprocessava arquivo órfão de rodada anterior**:
   `processed/run.py` varria `texto_bruto/*.txt` direto do disco, sem
   restringir ao Staging da rodada atual — documento que saiu da amostra
   (excluído por um filtro mais novo, ou não sorteado de novo) continuava
   sendo aprovado silenciosamente, sem nenhuma falha logada. Só não vazou
   pro corpus final por acidente (o `inner join` do `curated/build.py` com
   o Staging os descartou). Corrigido: `processed/run.py` agora restringe
   `arquivos_brutos` aos `doc_id` presentes no Staging atual (achado real:
   14 arquivos órfãos ignorados na re-execução).

6. **Métrica de página/OCR zerava em reprocessamento com cache**: quando
   `processed/run.py` roda sem precisar reextrair PDF (cache de
   `texto_bruto` já existe — o caso comum), as colunas `paginas` e
   `paginas_ocr` de TODOS os documentos ficavam zeradas no
   `documentos.parquet`, porque `stats_extracao` só era populado para o
   que foi extraído NESSA execução, nunca persistido entre execuções.
   `docs_com_ocr` no relatório dava 0 mesmo com dezenas de documentos
   usando OCR de verdade. Não afetava o texto nem `no_corpus`, só a
   métrica descritiva no relatório/DATACARD. Corrigido: `extract.py` agora
   grava `data/processed/<area>/extracao_stats.jsonl` (ledger, igual ao
   `manifesto.jsonl` da Raw) a cada extração, e `run.py` carrega esse
   histórico e mescla com o resultado da execução atual antes de montar as
   métricas. Precisou reextrair os 3.460 PDFs uma vez pra repopular o
   ledger vazio (sem rede, só CPU/OCR local).

7. **RAG estourava memória e matava o processo**: `gerar_rag` (Curated)
   montava os ~150 mil chunks inteiros (quase o corpus inteiro reformatado
   com sobreposição de 10%, mais metadado duplicado por chunk) numa lista
   Python e só then criava um DataFrame gigante — matou o processo em
   segundo plano por falta de memória, sempre no mesmo ponto (logo depois
   de SFT), 2 vezes seguidas. Corrigido: grava em lotes de 200 documentos
   direto num `pyarrow.parquet.ParquetWriter`, sem nunca materializar mais
   que um lote na memória.

Pendente: a janela de datestamp `2026-02-25..2026-06-25` falhou com HTTP 500
persistente durante a colheita de metadado e foi pulada sem retry — número de
registros de Saúde perdidos nessa janela é desconhecido. Ainda acontece
(reproduzido de novo em 2026-09-11/12, mesmo endpoint, mesmo erro).

`config/config.yaml` com `inventario.amostragem.n_alvo=5000` (era 500 no
commit inicial) — é o que produziu a terceira rodada acima. Commitado pelo
usuário em `1f2c355` ("primeira rodada"), junto com os consertos 3–7.

## Versão final (em andamento desde 2026-09-13)

Plano completo, com fases e checkboxes: `docs/PLANO_VERSAO_FINAL.md` —
**ler antes de continuar qualquer trabalho**. Decisões do usuário: crescer
até 20 mil PDFs usando o inventário da BDTD montado pelo grupo
(`data/externo/inventario_saude.csv.gz`, 183.718 fichas),
aplicando os filtros de escopo deste projeto; verificação final de PII no
Curated que para o pipeline com erro. Entrega da disciplina: código +
relatório de como o pipeline funciona (com o protocolo de coleta); os dados
NÃO são entregues — prioridade é código correto, testado e reprodutível.
Backup antes das mudanças:
`~/.vcoleta/backups/{processed,curated}_saude_2026-09-13.tar.gz` (os
`.zip` na raiz do projeto estão vazios — não são backup).

8. **Anonimização ainda destrói conteúdo científico** (achado 2026-09-13,
   ainda não corrigido). Recuperando o valor original atrás das máscaras
   no `texto_bruto`: `TITULO_ELEITOR` (863) são ORCID e DOI; `PLACA` (478)
   são nome de gene (`CYP2C19`) e sigla+ano de estudo (`OMS-2008`,
   `GBD-2017`, `HEI-2010`); `CARTAO_SUS` (266) e `PIS_PASEP` (270) são DOI
   (`1413-81232018236`) e código de setor censitário; `TELEFONE` (580) é
   quase todo real (comitê de ética, contato de pesquisador), com falso
   positivo em intervalo de anos quebrado em linha. Título e resumo que vão
   para SFT/benchmark não passam pelo anonimizador. Por isso a correção da
   anonimização vem ANTES da expansão para 20 mil (senão o erro se
   multiplica por ~7) e antes de ligar a verificação que para com erro
   (senão ela para por alarme falso).
9. **Exclusão de escopo por trecho de palavra** (achado 2026-09-13 pelos
   testes da Fase 1, corrigido): o conserto 3 comparava substring, e o
   termo `"equina"` casava dentro de "catequina" — 2 dos 39 documentos
   excluídos como zootecnia caíram só por isso. Agora a exclusão exige
   palavra inteira (`bate_algum_termo` em `src/raw/fontes.py`, usado na
   colheita e na Processed) e cada flexão precisa estar listada no
   `excluir_assunto`; a inclusão continua por trecho, para aceitar radical.
10. **Par de SFT com a resposta dentro da pergunta** (achado 2026-09-13
    lendo pares, corrigido): o template "resuma o trecho" usava as 600
    primeiras palavras do texto tratado como trecho e o resumo como
    resposta — mas o texto tratado COMEÇA no RESUMO (o corte de
    pré-textuais para ali). 186 de 243 pares do treino eram cópia.
    `_trecho_depois_do_resumo` em `curated/build.py`.
11. **Coletor cego para DSpace 7** (achado no piloto 2, 0 de 180 PDFs,
    corrigido): UFRN serve só a casca do Angular (sem link) → fallback pela
    API REST `/server/api` (`fulltext._descobrir_dspace7`); Fiocruz publica
    `citation_pdf_url` com `http://localhost:4000` → `_no_mesmo_site` troca
    pelo domínio da página. UFPR: servidor de handles fora do ar (HTTP 500),
    retirada do piloto.
12. **Telefone real escapando + RAG criando PII falsa** (achado pela
    verificação final do Curated, que PAROU a Fase 6 com 35 ocorrências,
    todas no RAG; corrigido): telefone quebrado em linha depois do DDD
    (`(31)↵3xxx-xxxx`) não era detectado — vazamento que existia no
    pré-treino também, só visível no RAG porque `_chunkar` juntava linhas
    com espaço; e essa junção criava telefone/CPF falso a partir de tabela.
    Agora a quebra de linha vale como separador só depois de `(DD)` ou
    `+55 DD`, e o RAG recorta o texto original preservando as quebras.
    Auditoria da regra nova sobre os textos já tratados: 17 telefones a
    mais, todos reais, nenhum falso.
13. **SFT: trecho depois do resumo é o ABSTRACT** (achado lendo pares
    depois do reprocessamento final, corrigido): 109 de 178 pares "leia o
    início" eram tradução disfarçada; `_e_portugues` aceitava inglês porque
    "a", "as", "do", "no" também são palavras inglesas. Agora o trecho
    começa no título INTRODUÇÃO do corpo (`_trecho_da_introducao`, último
    título nos primeiros 40% do texto, pula o sumário), a trava compara
    stopwords pt × en e `_limpar_palavras_chave` tira `CNPQ::...`.
14. **10 teses de Saúde excluídas como zootecnia** (8 voltaram ao corpus; 2
    de odontologia seguem fora por idioma inglês) (achado revisando à mão
    os 42 excluídos, com o termo que derrubou cada um; corrigido). A
    auditoria da 3ª rodada tinha dado os 39 como "todos zootecnia" só pelos
    títulos — estava errado. Causas: "saneamento" (saúde pública; saiu da
    lista), "pé equino"/"tratamento do equino" (ortopedia infantil), dentina
    bovina (odontologia in vitro), soro fetal bovino, albumina sérica
    bovina, tripsina bovina (reagentes). Nova seção `escopo.expressoes_permitidas`
    no config, apagada do texto antes da checagem (`fontes.bate_exclusao`,
    usado na colheita OAI, no inventário BDTD e na Processed). Fronteira
    declarada, continuam fora: vaccinia bovina (2) e doenças vesiculares.

Estado em 2026-09-13 ~05h: Fase 6 reprocessou (2.841 docs, 69,24 M
palavras, PII 4.719) e a verificação parou com erro (defeito 12, já
corrigido). Piloto 3 (UFRN + Fiocruz, mesmos 120 candidatos, 04:47–05:09):
119 de 120 PDFs (UFRN 60/60, Fiocruz 59/60). Documentos do inventário BDTD
chegam sem resumo e sem programa (o CSV não tem) e com instituição em sigla.

**Estado final (2026-09-13 07:05), depois dos defeitos 10–14:** reprocessamento
local (staging, processed, curated) com **verificação de PII no Curated: 0
ocorrências em 11 arquivos**. Corpus: 2.951 documentos (UFMG 2.845, Fiocruz
54, UFRN 52), 72,03 M palavras, mediana 20.546; 631 reprovados (445 inglês,
150 linhas repetitivas, 32 fora de escopo — todos UFMG, zootecnia de fato),
3 duplicatas exatas, 0 fuzzy, 0 contaminação; PII mascarada 4.937. Curated:
pré-treino 2.652/150/149; SFT 882/55/41 (978; 220 pares de introdução, 0
cópias); RAG 155.312 chunks; benchmark 292/292/200. Coleta: 3.596 PDFs
(UFMG 3.477, UFRN 60, Fiocruz 59). 128 testes. Relatório
`docs/RELATORIO_ATIVIDADE_02.md` + `.pdf`. Patches e mensagens de commit em
`~/.vcoleta/backups/patches/`.

**Coleta até 20 mil PDFs — AUTORIZADA pelo usuário em 2026-09-13 (~13h).**
Código novo (145 testes, patch `fase10-coleta20k-codigo.patch`):
`src/raw/robots.py` (robots.txt pela letra e pelo espírito: veto a robôs de IA,
desafio anti-robô, bloqueio, 401/403/429/5xx → domínio fora), download
paralelo por instituição em rodadas de 200, disjuntor por instituição (erro
> 30% após 20 tentativas), manifesto gravado item a item. Config: meta_pdfs
20000, 800 candidatos por instituição, UFPR excluída. Etapas em tmux
`coleta20k`: `logs/coleta20k_1_robots.sh` (evidência de robots.txt) →
revisar vetos à mão → `logs/coleta20k_2_inventario.sh` (local) →
`logs/coleta20k_3_download.sh` (rede). Cada etapa grava
`logs/coleta20k_N_*.status`. Depois: staging/processed/curated e ler textos.
Andamento: etapas 1 e 2 ok (13:26–13:50). 1ª execução do download
(13:51–14:40) chegou a 8.748 PDFs e o disjuntor cortou 26 instituições;
diagnóstico → 19 suspensas no config (`coleta.instituicoes_suspensas`, com
motivo) e 7 defeitos do coletor corrigidos (DSpace 7 via assets/config.json,
handle não numérico, bitstream que devolve HTML, metatag com IP:4000, barra
dupla, desafio anti-robô na página). 155 testes. 2ª execução relançada às
14:40 no tmux `coleta20k` (monitor com marcador `logs/.reinicio_coleta20k`).
**Coleta encerrada às 17:45: 15.098 PDFs** (meta reduzida para 15 mil pelo
prazo, decisão do usuário; 4 execuções, a última com o disjuntor partindo do
histórico, 156 testes). Depois, Staging/Processed/Curated com uma **amostra de
5.023 PDFs** (`processed.amostra`: os 3.582 já extraídos + até 40 sorteados por
instituição; 18:53–20:05): 4.219 documentos de 62 instituições, 98,8 M
palavras, PII 0 na verificação, 157 testes. Limitação achada lendo: ~7 das 18
exclusões de escopo em documentos sem resumo eram Saúde (sobrenome "Bezerra"
casa com o termo "bezerra"; "recursos hídricos" em estudo de dengue). Relatório reescrito mais objetivo; PDF
gerado por `docs/gerar_pdf_relatorio.py` (HTML → ODT → PDF, corpo justificado,
linhas de tabela inteiras, conferência automática de texto cortado).
Backups do piloto 2: `data/reports/saude/raw_piloto2.json`,
`data/raw/saude/{manifesto,inventario}.piloto2.jsonl`.

Testes: `python -m pytest` (pasta `tests/`, tudo em diretório temporário —
nenhum teste escreve em `data/`). NUNCA rodar `tests/gerar_dados_sinteticos.py`
sem ler antes: ele APAGA as quatro camadas de `data/` para gerar dados falsos.

## Regras invioláveis de coleta

- **Nunca aumentar `requisicoes_por_segundo` ou `rps_repositorios` acima do
  que está no config.** Se algo estiver lento, a resposta é esperar, não
  acelerar.
- **Nunca desabilitar `verify` de TLS nem `respeitar_robots`.**
- **Sempre rodar `preflight.py` antes de qualquer coleta**, e parar se houver
  bloqueio.
- **`Crawl-delay` do `robots.txt` vale para TODOS os caminhos de rede**, não
  só download. Já causamos bloqueio na UNIFESP por violar isso.
- **Nunca rodar coleta sem eu autorizar na mensagem.**
- **Métrica boa não é prova: sempre ler alguns textos processados com o
  olho.** Cinco defeitos deste pipeline foram achados assim, nenhum por
  métrica.

## Regras de git

- **Nunca rodar `git commit` nem `git push`.** Um commit feito por mim
  carrega trailer de coautoria do Claude — mesmo só local, sem eu dar
  push. Se o usuário depois empurrar esse commit (é o que ele vai fazer),
  o nome do Claude aparece no histórico público do GitHub de qualquer
  jeito. Já aconteceu uma vez nesse projeto.
  Eu posso preparar tudo (`git init`, `git add`, redigir a mensagem de
  commit), mas quem roda o `git commit` e o `git push` é o usuário, na
  própria máquina dele — nunca eu pela ferramenta Bash.

## Regras de redação (relatório, protocolo, README, código)

- **O trabalho é do grupo como um todo.** Nada de créditos individuais nem de
  "o colega fez X": escrever "o grupo", "montado pelo grupo". Nomes só na
  lista do grupo, em ordem alfabética e com primeiro e último nome:
  **Eduardo Melo, Otávio França e Ygor Morais**.
- Relatório final (entrega de 2026-09-14): coleta de 15.098 PDFs; corpus e
  produtos da amostra de 5.023 PDFs, declarada.
