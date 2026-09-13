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

`config/config.yaml` ainda tem `inventario.amostragem.n_alvo=5000` não
commitado (era 500 no commit inicial) — é o que produziu a terceira rodada
acima. Se for commitar, revisar junto com o resto do estado do piloto.

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
