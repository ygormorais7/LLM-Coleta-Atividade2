# Plano da versão final — bdtd-corpus

Criado em 2026-09-13. Marque `[x]` ao terminar cada item. Uma fase por vez.

## Decisões já tomadas

- **Meta:** chegar a **20 mil PDFs baixados**, crescendo com o inventário da
  BDTD montado pelo grupo (`inventario_saude.csv.gz`, 183.718
  fichas), **aplicando os filtros de escopo deste projeto**.
  Observação: pela taxa atual de reprovação na Processed (~18%), 20 mil PDFs
  viram ~16,4 mil documentos no corpus final.
- **Verificação final de dados pessoais no Curated:** se encontrar algo,
  **para o pipeline com erro**.
- **Usar o inventário do grupo:** sim, com justificativa no protocolo.
- **O que é entregue:** o **código** e um **relatório** explicando como o
  pipeline funciona, incluindo o protocolo de coleta. **Os dados não são
  entregues.** Consequência: o que pesa é código correto, testado e
  reprodutível, e relatório/protocolo claros. A coleta completa até 20 mil
  (Fase 8.4) serve para validar o pipeline em escala e dar números ao
  relatório — **a decidir** se vai até o fim ou para no piloto (8.3).

## Ponto de partida

- [x] Commit do estado atual (`1f2c355 primeira rodada`), feito pelo usuário.
- [x] Backup verificado em `~/.vcoleta/backups/`:
  `processed_saude_2026-09-13.tar.gz` (6.351 arquivos) e
  `curated_saude_2026-09-13.tar.gz` (13 arquivos).
- [ ] Apagar `processed_saude.zip` e `curated_saude.zip` da raiz do projeto:
  estão **vazios** (só a pasta, sem arquivos) e não são backup.

## Pendências que só o usuário resolve

- [x] Formato da entrega: código + relatório (com protocolo). Dados não são
  entregues.
- [ ] Data de entrega (define até qual fase ir).
- [x] Uso do inventário do grupo: liberado.
- [x] Links que falharam no teste manual (2 dos 4 anotados), ambos da
  Anhembi, sistema TEDE:
  `https://sitios.anhembi.br/tedesimplificado/handle/TEDE/1774` e
  `https://sitios.anhembi.br/tedesimplificado/handle/TEDE/1762`.
  Usar no piloto da Fase 8 para diagnosticar (site fora do ar, bloqueio ou
  endereço antigo).

## Regras que valem em todas as fases

1. Uma fase por vez; cada fase termina com **commit feito pelo usuário**.
2. Testes passando antes do commit (a partir da Fase 1).
3. Backup de `data/processed` e `data/curated` antes de reprocessar.
4. Nada que acesse a internet sem `preflight.py` **e** autorização explícita.
   Fases 1 a 6 são 100% locais.
5. Depois de reprocessar, ler textos com o olho — não confiar só em número.

---

## Diagnóstico que motivou a ordem (2026-09-13)

**Varredura do Curated:** 31 alarmes, todos falsos.

**Máscaras no texto das teses** (valor original recuperado do `texto_bruto`,
595 documentos examinados):

| Detector | Ocorrências | O que era de verdade | Veredito |
|---|---:|---|---|
| `TITULO_ELEITOR` | 863 | ORCID (`0000-0002-8214`), DOI (`0034-7167-2016`) | falso |
| `PLACA` | 478 | gene `CYP2C19`; sigla+ano: `OMS-2008`, `GBD-2017`, `HEI-2010`, `PNS-2019`, `NRS-2002` | falso |
| `CARTAO_SUS` | 266 | DOI (`141381232017224`), setor censitário IBGE (`310170605000006`), eixo de gráfico | falso |
| `PIS_PASEP` | 270 | DOI da Ciência & Saúde Coletiva (`1413-81232018236`) | falso |
| `TELEFONE` | 580 | quase todo real: comitê de ética `(31) 3xxx-xxxx`, contato de pesquisador; falso em intervalo de anos quebrado em linha (`2008`↵`2009`) | ok, ajuste fino |

**Consequência:** o conserto da anonimização vem ANTES da expansão (senão o
erro se multiplica por ~7) e antes da verificação que para com erro (senão ela
para por alarme falso).

## Números da meta de 20 mil

| Etapa sobre o CSV do grupo | Fichas |
|---|---:|
| Total | 183.718 |
| Acesso aberto e com link | 160.801 |
| Fora da UFMG (já coberta via OAI) | 155.537 |
| Passa no `filtro_assunto` (título + assuntos) | 63.987 |
| Depois do `excluir_assunto` | **61.581** |

- 139 instituições, 158 domínios; 6.477 links passam por `hdl.handle.net`.
- Faltam ~16,5 mil PDFs (já temos 3.474).
- Taxa de sucesso esperada entre 33% (teste manual: 2 de 6) e 50% (download do
  grupo: 419 de 831) → entre ~33 mil e ~50 mil tentativas. Folga pequena
  sobre os 61,6 mil candidatos.
- Disco: PDF médio atual 4,11 MB → ~68 GB a mais. Livre: 899 GB.
- Tempo: ~2 requisições por candidato a 1 a cada 3 s **por site**. Um site
  por vez (como o harvest faz hoje): ~55 a 85 horas. Vários sites em paralelo,
  cada um no mesmo ritmo de 3 s: a maior fila (UFSC, 4.093 candidatos) leva
  ~7 horas. Paralelizar entre sites diferentes **não** aumenta o ritmo em
  nenhum site, então não fere a regra de não acelerar.

---

## Fase 1 — Rede de segurança: testes do que já foi corrigido (concluída em 2026-09-13)

- [x] Instalar `pytest` no ambiente `coleta` e registrar em `requirements.txt`.
- [x] `tests/test_anonimizacao.py`: código de procedimento `0101020058`,
  `PEG6000` e eixo de anos não são mascarados; telefone e placa reais são.
- [x] `tests/test_escopo.py`: "raiva bovina" e "novilhos Nelore" excluídos;
  "catequina" não.
- [x] `tests/test_processed_run.py` (no lugar de `test_processed_orfaos.py`):
  órfão ignorado, páginas vindas do histórico, zootecnia fora e catequina
  dentro — tudo em diretório temporário, nunca em `data/`.
- [x] `tests/test_extracao_stats.py`: a extração grava o histórico de páginas.
- [x] `tests/test_rag.py`: gravação em lotes, com `ano` vazio no 2º lote.
- [x] 28 testes passando. Patch: `~/.vcoleta/backups/patches/fase1-testes.patch`.

**Defeitos que os testes pegaram:**
1. A exclusão de escopo comparava trecho de palavra: `"equina"` casava dentro
   de "catequina". 2 dos 39 documentos excluídos como zootecnia caíram só por
   isso (1 deles volta ao corpus na Fase 6). Corrigido: exclusão por palavra
   inteira (`bate_algum_termo` em `src/raw/fontes.py`, usado na colheita e na
   Processed); flexões que faltavam (`rebanhos`, `silagens`) no config.
2. No conserto acima, uma variável do laço de `processed/run.py` tinha o mesmo
   nome da função de escopo e quebrava a execução. Pego pelo teste antes de
   rodar sobre os dados reais.

## Fase 2 — Precisão da anonimização (prioridade nova)

Arquivos: `src/processed/clean.py`, `config/config.yaml`,
`tests/test_anonimizacao.py`.

- [x] Antes dos detectores numéricos, **pular trechos que são URL, DOI ou
  ORCID** (`https://…`, `doi:`, `10.xxxx/…`, `orcid.org/…`). E-mail e perfil
  de rede social continuam sendo detectados antes disso.
- [x] Validar por **dígito verificador** (como já é feito com CPF e CNPJ):
  título de eleitor (regra do TSE, com UF 01–28), PIS/PASEP e cartão SUS
  (começa com 1, 2, 7, 8 ou 9; soma ponderada divisível por 11).
- [x] `PLACA`: desligada no config (`placa_veiculo: false`), com justificativa.
- [x] `TELEFONE`: sem quebra de linha como separador e com validação de DDD
  (sem zero), fixo começando com 2–5, celular com 9, e intervalo de anos
  (`2008-2009`) recusado.
- [x] Testes com os casos reais do diagnóstico e com números válidos gerados
  pelo algoritmo oficial. 48 testes passando. Patch:
  `~/.vcoleta/backups/patches/fase2-anonimizacao.patch`.
- [x] Diagnóstico de novo sobre o `texto_bruto` das 2.840 teses do corpus
  (máscaras antes → depois): título de eleitor 863 → 0; placa 478 → 0; cartão
  SUS 266 → 1; PIS/PASEP 257 → 8; telefone 580 → 394; CEP 657 → 649; CPF 15 → 9;
  CNPJ 5 → 4; RG 20 → 15; e-mail (1.524) e perfil social (18) inalterados.
  Amostras lidas à mão: telefones restantes são de comitê de ética e de
  pesquisadores (reais); CPFs restantes estão em folhas de assinatura de TCLE
  (reais — o corte de anexos não pega todas); os 15 de RG eram todos parâmetro
  de espectro de RMN ("RG" = ganho do receptor) → corrigido junto com a Fase 5
  (RG exige 7 a 10 dígitos); PIS e cartão SUS restantes são números de tabela
  que passam no dígito verificador por acaso (~1 em 11).
- [x] `pytest` passando → commit.

## Fase 3 — Consertos no Curated

Arquivos: `src/processed/run.py` e/ou `src/curated/build.py`, testes.

- [x] **Anonimizar título e resumo** antes de irem para SFT e benchmark: a
  Processed grava `metadados.parquet` (título e resumo anonimizados, contagem
  em `pii_ocorrencias_metadados`) e a Curated lê de lá, nunca da Staging.
- [x] Trava de idioma também no resumo/trecho que vai **dentro da pergunta**
  do SFT.
- [x] "Fonte" honesta: `_fonte()` diz `OAI-PMH <repositório>` ou
  `inventário BDTD → <repositório>`, por documento e no DATACARD. O texto de
  anonimização do DATACARD foi atualizado com as regras da Fase 2.
- [x] 52 testes passando (`tests/test_curated.py` novo). Patch:
  `~/.vcoleta/backups/patches/fase3-curated.patch`.

## Fase 4 — Padronização (item 3 do enunciado)

Hoje o idioma aparece de 6 formas: Português (1.879), por (1.727), eng (21),
Inglês (2), fra (2), N/A (1).

- [x] `src/processed/padroniza.py` (novo): idioma → `pt/en/es/fr/it/de`; tipo →
  `dissertação de mestrado` / `tese de doutorado` (legível, porque entra no
  texto das instruções do SFT); ano → inteiro entre 1800 e o ano corrente.
  **Valor original guardado ao lado** (`*_bruto`).
- [x] `src/processed/run.py`: os metadados padronizados vão na mesma tabela
  `metadados.parquet` da Fase 3.
- [x] `src/curated/build.py`: `carregar_corpus` lê os metadados padronizados;
  DATACARD descreve a padronização.
- [x] `tests/test_padroniza.py` com cada variação encontrada no Staging.
- [x] 83 testes passando. Patch: `~/.vcoleta/backups/patches/fase4-padronizacao.patch`.

## Fase 5 — Auditoria de dados pessoais

- [x] `src/processed/clean.py`: `anonimizar` devolve cada ocorrência com o
  trecho em volta já mascarado (`achados`), com as máscaras de todos os
  detectores aplicadas no contexto.
- [x] `src/processed/run.py`: grava `data/processed/saude/pii_relatorio.parquet`
  (`doc_id`, `campo` = texto/título/resumo, `tipo`, `contexto`).
- [x] `src/curated/verificar_pii.py` (novo; `python -m src.curated.verificar_pii`):
  varre pré-treino, SFT, RAG, benchmark e índice com os mesmos detectores;
  ignora URL, ID, hash, caminho e autoria; grava
  `data/reports/saude/verificacao_pii_curated.json`; **sai com erro** se
  encontrar algo. (Ficou em `src/curated/` em vez de `scripts/`, para rodar
  também como etapa do pipeline.)
- [x] `run_pipeline.py`: roda a verificação ao fim do Curated e devolve código 1
  se houver ocorrência.
- [x] RG: exige 7 a 10 dígitos terminando em dígito (falsos de RMN do diagnóstico
  da Fase 2; também deixou de engolir o espaço seguinte).
- [ ] (Opcional, não feito) método e escore de cada duplicata. O
  `documentos.parquet` já registra `duplicata` e `duplicata_de`.
- [x] 89 testes passando. Patch: `~/.vcoleta/backups/patches/fase5-auditoria-pii.patch`.

## Fase 6 — Reprocessar e conferir (local, sem rede)

- [x] Backup de `data/processed` e `data/curated` (`~/.vcoleta/backups/`).
- [x] `run_pipeline.py --camadas processed curated` (04:03–04:52):
  2.841 documentos (backup: 2.840; +1 é a tese de catequina que voltou),
  69,24 M palavras; máscaras de PII 7.961 → 4.719; 617 reprovados por
  qualidade (37 por escopo), 2 duplicatas; RAG 149.243 trechos.
- [x] Ler 20 linhas do `pii_relatorio.parquet` e pares de SFT. PII: todas
  reais (e-mail, CEP e telefone de afiliação e de comitê de ética). SFT:
  **defeito novo** — no par "resuma o trecho", a resposta vinha copiada dentro
  da pergunta (186 de 243 no treino), porque o texto tratado começa no RESUMO.
  Corrigido (`_trecho_depois_do_resumo`) com teste.
- [x] **A verificação final PAROU o pipeline com erro**: 35 ocorrências
  (33 telefones, 2 CPFs), todas no RAG. Duas causas: (1) telefones reais
  quebrados em linha depois do DDD (`(31)↵3xxx-xxxx`, `+55 31↵3xxx-xxxx`)
  escapavam da anonimização — vazamento que existia também no pré-treino, só
  visível no RAG; (2) o RAG juntava as linhas com espaço e criava números
  falsos a partir de tabela (`1999↵9889 6596`). Corrigido: quebra de linha
  aceita só depois de DDD entre parênteses ou `+55 DD`; o RAG recorta o texto
  original preservando as quebras. 118 testes.
- [x] Reprocessamento final (05:09–06:03, staging, processed, curated):
  2.943 documentos, 71,8 M palavras; **verificação de PII: 0 ocorrências**.
- [x] Leitura depois do reprocessamento achou mais dois defeitos:
  (1) SFT: o trecho "depois do resumo" era o ABSTRACT (109 de 178 pares) →
  trecho a partir do título INTRODUÇÃO; trava de idioma pt × en; palavras-chave
  sem `CNPQ::` (patch `fase6-sft-introducao.patch`); (2) escopo: 10 teses de
  Saúde excluídas como zootecnia ("saneamento", "pé equino", dentina bovina,
  reagentes) → `escopo.expressoes_permitidas`.
- [x] Reprocessar com os dois consertos (06:13–07:05): 2.951 documentos,
  72,03 M palavras; 8 das 10 teses de Saúde voltaram (2 seguem fora por
  inglês); SFT 978 pares (220 de introdução, 0 cópias, 1 pergunta em inglês);
  RAG 155.312; **verificação de PII: 0 ocorrências em 11 arquivos**.
- [x] `CLAUDE.md` e DATACARD atualizados (DATACARD é regenerado pelo Curated).

## Fase 7 — Declarar o que se perdeu na coleta

- [x] Código (local): `ClienteOAI._colher_janela` divide ao meio a janela que
  falha, até 1 dia; o que não se recupera vai para `janelas_perdidas` e para o
  relatório do inventário; **5 falhas seguidas sem registro novo interrompem a
  colheita** (critério de parada do protocolo). Comando novo
  `python -m src.raw.inventario janela --de … --ate … [--prefixo oai_dc]`
  recolhe só o intervalo e junta ao inventário o que faltava, sem reamostrar.
  Testes com servidor simulado. Patch: `fase7-janela-codigo.patch`.
- [x] **Incidente (2026-09-13 04:12–04:14):** a primeira execução autorizada
  recebeu HTTP 500 da UFMG em todo recorte da janela, até 1 dia — o defeito não
  é paginação profunda. Interrompida manualmente após 15 requisições com falha,
  antes de existir o disjuntor (que nasceu desse incidente).
- [x] **Diagnóstico** (`logs/fase7_diagnostico.py`, ~10 requisições,
  `data/reports/saude/diagnostico_janela_ufmg.json`): `ListIdentifiers` funciona
  e conta **755 registros** (+2 excluídos) no set `com_1843_6` nessa janela — pela
  proporção de Saúde do resto da coleta (~9,5%), algo como 70 de Saúde. A mesma
  janela em **`oai_dc` responde**: o defeito do servidor é só no formato `dim`.
- [x] Recuperação (rede, 04:23): janela em `oai_dc`. A primeira página responde,
  mas a paginação volta a dar HTTP 500; o **disjuntor parou a colheita sozinho
  após 5 falhas seguidas**. Obtidos 235 registros → 13 de Saúde → 9 já estavam
  no inventário, **4 novos** (4 com bitstream via ORE). Perda declarada em
  `data/reports/saude/inventario_janela.json` (6 subjanelas): cerca de 520 dos
  755 registros da janela seguem não colhidos (~50 de Saúde, pela proporção).
  Recuperação registro a registro (`GetRecord` para ~520 identificadores de um
  servidor que está falhando) ficou como trabalho futuro.

## Fase 8 — Expansão para 20 mil PDFs com o inventário do grupo

Pré-requisito: Fases 1–6 concluídas.

**8.1 Código (local)**
- [x] Copiar o CSV para `data/externo/inventario_saude.csv.gz` (fica fora do
  git pelo `.gitignore`).
- [x] `src/raw/fontes.py` + `src/raw/inventario.py`: nova fonte que lê o CSV
  e gera candidatos; `config/config.yaml` com a seção dessa fonte,
  **excluindo UFMG** (já vem via OAI, com identificadores diferentes).
- [x] `excluir_assunto` de todas as fontes (OAI e inventário BDTD) somado em
  `_termos_exclusao_escopo` (`src/processed/run.py`). O `filtro_assunto` ficou
  por fonte (os dois comparam trecho, então radical funciona; só a exclusão
  compara palavra inteira).
- [x] Checagem de escopo na Processed olha também o início do texto extraído
  (o CSV não tem resumo, e foi pelo resumo que a zootecnia foi pega).
- [x] **`filtro_assunto` aceitar variações das palavras.** Hoje só casa a
  palavra inteira: "odontologia" não pega "odontológico" — achado real: o
  link `TEDE/1762` ("Hospitalidade e humanização no atendimento
  odontológico") é de Saúde e fica de fora. Medido no CSV (2026-09-13): com
  radicais (`enfermag`, `medic`, `odontolog`, `farmac`, `nutric`,
  `epidemiolog`, `obstetr`, `fisioterap`…) os candidatos sobem de 61.581
  para **70.982** (+9.401). Amostra de 25 títulos a mais, lida à mão: 22 de
  Saúde, 2 duvidosos (fármacos em água de superfície; gestão de resíduos de
  hospital), 1 fora (gestão organizacional). **Armadilhas de radical, testar
  cada uma:** `medic` casa com "medição" (engenharia); `hospital` casa com
  "hospitalidade" — é por isso que o rótulo do inventário deu relevância "alta"
  a `TEDE/1774`, uma tese de gastronomia. Não usar `hospital` como radical.
- [x] `src/raw/fulltext.py`: depois de redirecionar pelo `hdl.handle.net`,
  checar `robots.txt` e aplicar ritmo **no site final** (redirecionamento
  seguido à mão em `_obter`).
- [x] `src/raw/harvest.py`: sites diferentes em paralelo, cada um no mesmo
  ritmo (`RateLimiter` reserva horário por domínio); parar ao atingir
  `coleta.meta_pdfs`.
- [x] `preflight.py`: exigir evidência de `robots.txt` para cada domínio do
  inventário BDTD (`checar_evidencia_bdtd_csv`).
- [x] 106 testes passando. Patch: `fase8-inventario-bdtd-codigo.patch`.

**8.2 Protocolo**
- [x] Evidência de `robots.txt` dos domínios do piloto
  (`evidencia_robots_*.json`).
- [x] `docs/PROTOCOLO_DE_COLETA.md` v2.0: justifica o uso do inventário do
  grupo (feito pela API, não pela busca bloqueada).

**8.3 Piloto (rede, com autorização)**
- [ ] ~300 candidatos de 5 instituições com sistemas diferentes (DSpace, TEDE,
  via `hdl.handle.net`), em tmux. **Incluir sites TEDE**: são 12.268
  candidatos em 40 domínios (~20% do conjunto filtrado; maiores:
  `tede2.pucrs.br`, `repositorio.bc.ufg.br`, `tede.ufam.edu.br`). Os 2 links
  que falharam no teste manual são da Anhembi (TEDE, endereço `http://`), mas
  a Anhembi tem só 10 fichas no CSV inteiro e 1 no conjunto filtrado — não
  pesa na meta.
- [x] Piloto 1 (04:23): PUC-RS (veta robôs de IA) e UFSC (desafio Cloudflare)
  excluídas antes de baixar qualquer arquivo.
- [x] Piloto 2 (04:27): **0 de 180** (UFRN, UFPR, Fiocruz). Diagnóstico com ~15
  requisições: UFRN = DSpace 7 sem renderização no servidor; Fiocruz =
  `citation_pdf_url` com `localhost:4000`; UFPR = servidor de handles fora do
  ar. Coletor corrigido (API REST do DSpace 7, troca do endereço interno);
  UFPR retirada. Patch: `fase8-piloto-coletor.patch`.
- [x] Piloto 3 (04:47–05:09), mesmos 120 candidatos: **119 de 120** (UFRN
  60/60, Fiocruz 59/60).
- [x] Ler textos extraídos do piloto: 2 da UFRN e 2 da Fiocruz (protocolo de
  analgesia em UTI, fitoterápico anti-inflamatório, vigilância de arboviroses,
  farmácia hospitalar), todos de Saúde, com extração limpa, em português.
  Documentos do inventário chegam sem resumo e sem programa (o CSV não tem).
- [x] Reprocessar (staging, processed, curated) com a verificação passando:
  UFRN 52 e Fiocruz 54 documentos no corpus final.
- Sites TEDE não entraram no piloto (PUC-RS, o maior, foi excluída); ficam
  para a expansão.

**8.4 Coleta completa (rede, com nova autorização)**
- [x] Autorização do usuário (13/09/2026, ~13h).
- [x] Código para escala (145 testes): robots.txt pelo espírito automático,
  download paralelo por instituição em rodadas, disjuntor por instituição,
  manifesto item a item. Patch `fase10-coleta20k-codigo.patch`.
- [x] Etapa 1 (13:26–13:50): evidência de robots.txt de 179 domínios (com
  esquema) + 1 nova tentativa para 23 falhas passageiras (nenhuma voltou).
  Ficam 21.253 de 35.238 candidatos; saem 13.985 (inacessível 6.495, HTTP 403
  2.732, veto a robôs de IA 2.641, HTTP 468 1.306, 5xx 578, bloqueio total 187,
  desafio anti-robô 46). Vetos conferidos à mão: todos têm grupo explícito de
  robô de IA com `Disallow: /`. Tabela no protocolo, seção 3. Achado: links
  `http://localhost:4000` e `:8080` no CSV → `fontes.host_interno` os descarta.
- [x] Etapa 2 (13:50): inventário com 21.232 candidatos novos (total 24.988;
  BDTD 21.352 de 92 instituições; 405 estratos); 0 candidatos em domínio
  vetado ou endereço interno; backup `inventario.antes_bdtd_csv_20260913_1350.jsonl`;
  preflight com 0 bloqueios.
- [x] Etapa 3 (13:51–17:45, 4 execuções): **15.098 PDFs** (UFMG 3.477, piloto
  119, coleta em escala 11.502; 62 instituições). Meta reduzida para 15 mil pelo
  prazo, por decisão do usuário. Defeitos achados e corrigidos no caminho:
  variações de DSpace 7, barra dupla, desafio anti-robô na página, disjuntor sem
  histórico na retomada; 23 instituições suspensas com motivo.
- [ ] Reprocessar todas as camadas com os 15.098 PDFs; ler textos. **Não feito
  nesta entrega**, por decisão do usuário (prazo): o relatório traz os números da
  coleta, e o corpus e os produtos continuam os dos 3.596 PDFs, declarado.
- [ ] Verificação final passa → **commit**.

## Fase 9 — Documentação da entrega

- [x] `docs/RELATORIO_ATIVIDADE_02.md` (3 membros do grupo): como o pipeline
  funciona, protocolo resumido, armadilhas da API da BDTD, defeitos achados e
  corrigidos, incidentes e perdas declaradas,
  números finais, limitações.
- [x] PDF gerado com `python docs/gerar_pdf_relatorio.py` (LibreOffice).
- [ ] **Commit final — feito pelo usuário** (ver
  `~/.vcoleta/backups/patches/MENSAGENS_DE_COMMIT.md`).

---

## Mapa de arquivos por fase

| Arquivo | Fases |
|---|---|
| `src/processed/clean.py` | 2, 5 |
| `src/processed/run.py` | 3, 4, 5, 8 |
| `src/curated/build.py` | 3, 4 |
| `config/config.yaml` | 2, 8 |
| `run_pipeline.py` | 5 |
| `src/raw/fontes.py`, `src/raw/inventario.py` | 7, 8 |
| `src/raw/fulltext.py`, `src/raw/harvest.py`, `preflight.py` | 8 |
| `tests/*` (novos) | 1 a 8 |
| `docs/PROTOCOLO_DE_COLETA.md`, `docs/RELATORIO_ATIVIDADE_02.md` | 8, 9 |
