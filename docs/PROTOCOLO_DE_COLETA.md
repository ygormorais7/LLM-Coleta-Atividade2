# Protocolo de Coleta
<!--
> **Este documento deve estar preenchido e datado ANTES da primeira requisição.**
> Um protocolo escrito depois da coleta não é protocolo, é descrição — você já
> sabia o resultado quando escreveu. E, na prática, é ele que te diz onde parar
> enquanto coleta.
>
> Campos marcados **⚠ CONFIRMAR** só você pode preencher.
> Campos marcados **⏳ MEDIR** só existem depois do piloto — deixe-os
> explicitamente pendentes em vez de chutar.
-->
---

## 0. Identificação

| Campo | Valor |
|---|---|
| Projeto | `bdtd-corpus` — corpus de teses e dissertações da área de Saúde para adaptação de domínio de modelo de linguagem em português brasileiro |
| Responsável | Ygor Francisco de Carvalho Morais |
| E-mail de contato | ygor.morais@ufpi.edu.br |
| Instituição | Universidade Federal do Piauí — Centro de Ciências da Natureza — Departamento de Computação |
| Disciplina | Tópicos em Inteligência Artificial (DC/CCN072), 60h |
| Professor responsável | Prof. Raimundo Santos Moura (rsm@ufpi.edu.br) |
| Programa | SoberanIA |
| Data de início da coleta | 08/09/2026 |
| Versão deste documento | 1.0 |

---

## 1. Finalidade

### O que será feito com os dados

Construção de um corpus textual de teses e dissertações brasileiras da área de
Saúde, em português, para uso como **trabalho prático da disciplina
DC/CCN072**. O corpus alimenta quatro produtos, cada um correspondendo a um
conteúdo do plano de ensino:

| Produto do corpus | Conteúdo da disciplina |
|---|---|
| Camadas Raw → Staging → Processed | Aulas 2 a 4 — preparação de dados textuais: coleta e extração, padronização e normalização, limpeza e correção, deduplicação, anonimização |
| `curated/benchmark/` | Aulas 5 e 6 — construção de benchmarks para tarefas de domínio |
| `curated/rag/` | Aulas 7 e 8 (embeddings) e Aulas 26 a 29 (arquiteturas e aplicações RAG) |
| `curated/pretreino/` | Aula 13 — pré-treinamento com dados não rotulados |
| `curated/sft/` | Aulas 16 e 17 — fine-tuning para seguir instruções |

Avaliação prevista: perplexidade em conjunto reservado e descontaminado,
recall@k e MRR em benchmark de recuperação, e acurácia em benchmark de
múltipla escolha com gabarito derivado de metadados bibliográficos.

### O que NÃO será feito

- **Não haverá redistribuição dos PDFs originais.**
- **Não haverá publicação do texto integral extraído**, exceto para o
  subconjunto com licença aberta explícita (ver seção 6).
- Não haverá uso comercial.
- Não haverá tentativa de identificar, contatar ou caracterizar indivíduos
  citados nos trabalhos, nem cruzamento com outras bases para esse fim.
- **Não haverá treinamento de modelo a partir do zero.** O volume disponível
  não sustenta isso: a razão compute-ótima estabelecida pelo Chinchilla é de
  cerca de 20 tokens por parâmetro, e um corpus de 3 a 5 mil teses
  (~150–300 M tokens) seria compute-ótimo para um modelo da ordem de 10 M de
  parâmetros — irrelevante. O uso correto do material é **pré-treino
  continuado e ajuste fino sobre um modelo aberto já existente**, com
  avaliação de adaptação de domínio.
- Não haverá coleta em massa por raspagem da interface de busca da BDTD
  (ver seção 3).

### Princípio orientador

O material da disciplina é explícito: dataset é o diferencial, e o objetivo é
**qualidade acima de quantidade**. Este protocolo assume isso como regra de
projeto: um corpus de 3 a 5 mil documentos com procedência auditável,
amostragem declarada e limitações medidas vale mais — como artefato técnico e
como trabalho avaliado — do que uma tentativa malfeita de coletar 183 mil.

---

## 2. Escopo e taxonomia

| Campo | Valor |
|---|---|
| Área | Saúde |
| Taxonomia adotada | `capes.area_avaliacao` |
| Valores incluídos | Medicina I, Medicina II, Medicina III, Saúde Coletiva, Enfermagem, Farmácia, Odontologia, Nutrição, Educação Física |
| Recorte temporal | 2015–2025 |
| Tipos | tese de doutorado, dissertação de mestrado |
| Idioma | português (filtro por detecção com limiar de confiança 0,65) |
| N alvo — piloto | 300 documentos |
| N alvo — corpus final | 3.000 a 5.000 documentos |

### Por que esta taxonomia e não outra

Três classificações concorrem e **nenhuma reproduz o número da outra**:

| Taxonomia | Origem | Problema |
|---|---|---|
| `capes.area_avaliacao` | Catálogo de Teses e Dissertações da CAPES, dados abertos | Não é área do conhecimento, é área de **avaliação** de programas |
| `capes.area_conhecimento` | Tabela CNPq | Preenchimento inconsistente nos metadados de repositório |
| Faceta "Saúde" da BDTD | Navegação interna do portal | **Não reproduzível de fora** — não há como recalculá-la a partir das fontes |

Adotamos `capes.area_avaliacao` porque tem fonte oficial em dados abertos,
valores publicados e estáveis, e permite que qualquer pessoa recalcule a
contagem. O número de referência do corpus é a contagem **nessa** taxonomia —
não os 183.781 da faceta da BDTD, que pertencem a outra classificação.

### Decisões de fronteira registradas

- **Educação Física está incluída.** Pertence ao colégio de Ciências da Saúde
  na CAPES, mas boa parte da produção é de treinamento esportivo e pedagogia,
  não de saúde clínica. Decisão: incluir, e marcar a área de avaliação em cada
  documento para permitir excluí-la depois sem recoletar.
- **Psicologia está excluída.** Fica em Ciências Humanas na CAPES, apesar da
  interface com saúde mental.
- **Medicina Veterinária está excluída.** Fica em Ciências Agrárias.

---

## 3. Fontes

Uma linha por fonte. A evidência de cada uma é o JSON gerado por
`python -m src.raw.inventario descobrir --base <url>`, que captura o
robots.txt **como estava na data da consulta**.

| # | Fonte | Endpoint | Protocolo | Verificado em | Tem ORE | Evidência |
|---|---|---|---|---|---|---|
| 1 | Repositório Institucional da UFPI | `https://repositorio.ufpi.br/oai/request` | OAI-PMH | 08/09/2026 | sim | `evidencia_https_repositorio_ufpi_br.json` |
| 2 | Repositório Institucional da UFMG | `https://repositorio.ufmg.br/server/oai/request` | OAI-PMH | 08/09/2026 | sim | `evidencia_https_repositorio_ufmg_br.json` |
| 3 | ARCA / Fiocruz | endpoint OAI não localizado | — | 08/09/2026 | — | `evidencia_https_www_arca_fiocruz_br.json` |
| 4 | Catálogo CAPES | dadosabertos.capes.gov.br | Dados abertos | ⏳ | n/a | `data/externo/capes/` |

Os robots.txt da UFPI e da UFMG bloqueiam apenas a interface de busca
(`/search`, `/discover`, `/search-filter`) e não restringem o caminho do OAI —
o mesmo padrão observado na BDTD. Isso confirma o desenho pressuposto por este
protocolo: consulta facetada é cara e fica fechada a robôs; o OAI-PMH é a via
prevista para colheita automatizada.

O ARCA/Fiocruz publica `Sitemap: http://localhost:4000/...` no robots.txt,
indicando frontend DSpace 7 com endereço interno exposto; o endpoint OAI não
respondeu em nenhum dos sete caminhos convencionais testados. Fonte adiada,
com pedido de indicação registrado na seção 9.

> Candidatos sugeridos para Saúde, a verificar com o comando `descobrir`:
> ARCA/Fiocruz (temático de saúde, grande, DSpace), mais dois ou três
> repositórios universitários com programas fortes na área.

### Base para coletar de cada uma

**Repositórios via OAI-PMH.** O Open Archives Initiative Protocol for Metadata
Harvesting existe especificamente para colheita automatizada de metadados por
máquinas, e o provedor o expõe voluntariamente. É a porta da frente para
robôs, não um contorno. O IBICT, aliás, opera a BDTD justamente colhendo esses
mesmos endpoints.

**Catálogo da CAPES.** Dados abertos publicados pelo governo federal, com
licença de uso explícita. Nenhuma questão de robots.txt se aplica.

### O que foi deliberadamente evitado

Coleta em massa pela interface de busca da BDTD. O `robots.txt` do portal
contém `Disallow: /vufind/Search/`, e ainda que a letra da regra não alcance
outros caminhos, o espírito é claro: não usar o portal para montar inventário
em escala. Como as fontes acima resolvem o inventário, não há motivo para
testar o limite. Consultas pontuais ao portal, quando necessárias para
validação manual, são feitas por navegador, por uma pessoa.

`robots.txt` (https://bdtd.ibict.br/robots.txt) completo no dia do início da coleta: 
User-agent: *
Allow: /
Disallow: /vufind/Search/

---

## 4. Conduta técnica

| Parâmetro | Valor adotado | Onde está configurado |
|---|---|---|
| User-Agent | `bdtd-corpus/1.0 (pesquisa academica; UFPI - SoberanIA; +mailto:<contato>) python-requests` | `src/common.py::Config.user_agent` |
| robots.txt | consultado e respeitado por domínio | `coleta.http.respeitar_robots: true` |
| Ritmo na fonte de metadados | 1 requisição a cada 2 s | `requisicoes_por_segundo: 0.5` |
| Ritmo por domínio de repositório | 1 requisição a cada 3 s | `rps_repositorios: 0.33` |
| Concorrência | 4 threads, com o limite por domínio valendo dentro delas | `harvest.py` |
| Retry | backoff exponencial; `Retry-After` respeitado; `503` do OAI tratado como controle de fluxo | `bdtd_client.py`, `fontes.py` |
| Tamanho máximo por arquivo | 120 MB | `tamanho_max_pdf_mb` |
| Teto do piloto | 300 documentos | `max_pdfs`, `limite` |
| ORE quando disponível | sim | `prefix_binarios: "ore"` |

**Sobre o ORE.** Quando o repositório oferece `metadataPrefix=ore`, o OAI
entrega a URL do arquivo diretamente e dispensa a requisição à página HTML do
registro. Isso **reduz pela metade a carga imposta ao servidor da
universidade** por documento coletado. Não é otimização, é conduta.

### Janela de coleta

madrugada ou fim de semana, fora do horário de
maior uso dos repositórios.

### Critérios de parada imediata

A coleta é interrompida, e o incidente registrado na seção 8, se ocorrer
qualquer um dos seguintes:

- HTTP 429 ou 503 persistente em um mesmo domínio após três ciclos de backoff;
- bloqueio por IP ou por User-Agent;
- **qualquer contato de administrador de repositório** — nesse caso, resposta
  no mesmo dia e suspensão até acordo;
- sinal de degradação do serviço (tempo de resposta subindo consistentemente);
- taxa de erro acima de 30% em um domínio, o que costuma indicar que estamos
  pedindo errado, não que o servidor está ruim.

---

## 5. Dados pessoais (LGPD)

### Enquadramento

Tratamento para fins exclusivamente acadêmicos, por instituição de ensino e
pesquisa, sem identificação de titulares e sem qualquer decisão que os afete.
Os dispositivos pertinentes da Lei 13.709/2018 são o Art. 4º, II, 'b'
(finalidade acadêmica), o Art. 7º, IV (realização de estudos por órgão de
pesquisa, garantida sempre que possível a anonimização), o Art. 5º, II
(definição de dado pessoal sensível, que inclui dado referente à saúde) e o
Art. 11 (tratamento de dados sensíveis).

### Comitê de ética em pesquisa

A Resolução CNS 510/2016 lista, entre as pesquisas que não são registradas nem
avaliadas pelo sistema CEP/CONEP, aquelas que utilizam informações de acesso
público e aquelas que utilizam informações de domínio público. Teses e
dissertações depositadas em repositório institucional aberto se enquadram
nessa descrição, e não haverá contato com participantes de pesquisa nem acesso
a dados não publicados.

### Política de anonimização

**Autoria não é anonimizada.** Autor, orientador e instituição são metadados
bibliográficos públicos — a tese é publicada com esses nomes e é assim que se
cita. Removê-los destruiria a proveniência do corpus sem qualquer ganho de
privacidade.

**O alvo é PII de terceiros no corpo do texto:** participantes de pesquisa,
pacientes, entrevistados. Em Saúde, isso inclui dado sensível.

| Medida | Situação |
|---|---|
| Corte de pré-textuais, incluindo agradecimentos | implementado (`cortar_pretextuais`) |
| **Corte de anexos e apêndices** | ligado (`cortar_pos_referencias: true`) |
| CPF e CNPJ, com validação de dígito verificador | implementado |
| E-mail, telefone, CEP, RG, cartão SUS, título de eleitor, PIS/PASEP | implementado |
| NER de nomes de pessoa | desligado — ver justificativa |
| Auditoria manual de amostra | 30 documentos |
| **Recall medido em amostra rotulada** | ⏳ MEDIR |

**Por que o NER de nomes fica desligado.** Texto acadêmico é denso em nomes
próprios legítimos: "segundo Minayo (2014)", "a técnica de Bardin", nomes de
escalas, síndromes e instituições. Um NER de pessoas mascararia todos eles,
degradando o texto sem ganho de privacidade — os nomes citados são referência
bibliográfica pública, não PII de terceiro. A maior concentração de nomes de
terceiros fica nos agradecimentos, já removidos pelo corte de pré-textuais, e
nos anexos, já removidos. O NER será reavaliado apenas se a auditoria manual
encontrar nomes de participantes de pesquisa sobrevivendo no corpo do texto.

**Por que cortar anexos nesta área especificamente.** Em teses de Saúde, os
apêndices concentram TCLE preenchido, instrumentos de coleta e descrição de
caso clínico. É a seção de maior risco de PII e a de menor valor para
pré-treino. O custo de cortar é quase zero; o risco evitado é o maior do
projeto.

### Limitação declarada: quase-identificadores

A combinação de idade, doença rara, município e ano permite reidentificação
sem que nenhum CPF ou nome apareça no texto. **Nenhum regex, NER ou
ferramenta de detecção de PII resolve isso** — é um problema de
reidentificação, categoricamente distinto de detecção de PII.

Consequência para a redação: o corpus **não é declarado anonimizado**.
Declara-se o recall medido dos detectores em amostra rotulada, e declara-se
este risco residual como conhecido e não mitigado por meios automáticos.

---

## 6. Direitos autorais

Cada tese tem licença própria, definida pela instituição de defesa e pelo
autor. O texto extraído é obra derivada: a licença governa publicá-lo tanto
quanto publicar o PDF.

**Acesso aberto não é licença de redistribuição.**
`info:eu-repo/semantics/openAccess` significa legível sem pagar. O que o autor
assina no depósito costuma ser autorização para **aquele repositório**
disponibilizar, não licença pública para terceiros redistribuírem.

| Produto | Política |
|---|---|
| PDF original | não redistribuído; permanece em disco local |
| Texto integral extraído | uso interno acadêmico, restrito à disciplina |
| Metadados + `sha256` + link de origem | publicável |
| Subconjunto com licença aberta explícita (CC-BY, CC-BY-SA, CC-BY-NC) | publicável — N = ⏳ MEDIR (____%) |

> **Meça esse percentual no piloto, não no fim.** Ele determina se o produto
> final é um corpus publicável ou apenas um corpus interno acompanhado de
> metadados públicos. Se der 8%, isso muda o que você promete na apresentação
> do seminário.

---

## 7. Retenção e descarte

| Item | Onde | Versionado no Git | Retenção | Descarte |
|---|---|---|---|---|
| PDFs originais | `data/raw/saude/pdf/` | não (`.gitignore`) | até o fim do semestre letivo | exclusão do diretório |
| Texto extraído e tratado | `data/processed/saude/texto/` | não | idem | idem |
| Inventário e manifesto | `data/raw/saude/*.jsonl` | **sim** (ver nota) | permanente | — |
| Relatórios de camada | `data/reports/saude/*.json` | **sim** | permanente | — |
| DATACARD e este protocolo | `docs/`, `data/curated/` | **sim** | permanente | — |

Os relatórios e o DATACARD ficam versionados porque são a prova de auditoria:
sem eles não há como responder por que um documento entrou ou saiu do corpus.

O manifesto contém apenas identificadores, URLs, hashes e status — nenhum
conteúdo protegido — e é versionado integralmente. O inventário é versionado
sem a coluna `resumo`, para manter a consistência com a política da seção 6
(metadados, hash e link são publicáveis; conteúdo não).

---

## 8. Registro de execução

Preencher a cada rodada. Junto com `data/reports/*.json` e o
`manifesto.jsonl`, é o que torna a coleta auditável.

| Data | Fonte | Requisições | Documentos obtidos | Incidentes | Observações |
|---|---|---|---|---|---|
| _(exemplo)_ 2026-09-08 | ARCA/Fiocruz | 82 | 38 | nenhum | piloto com `limite: 40`; ORE disponível, sem raspagem de HTML |
| 2026-09-10/11 | UFMG (`com_1843_6`, dim) | metadado: ~38.638 registros do set inteiro, filtrados para 3.719 de Saúde (9,6%); ORE: 3.719; PDF: ~520 tentativas | 508 PDFs (1,8 GB), taxa de resolução 97,7% | 1 janela de datestamp (`2026-02-25..2026-06-25`) falhou com HTTP 500 persistente e foi pulada sem retry — número de registros perdidos nessa janela é desconhecido | amostragem estratificada por `ies`+`ano_faixa`, `n_alvo=500`, 3 estratos, cota fechada em todos; 12 falhas de download (`conteudo_nao_e_pdf`/`pdf_nao_localizado`), documentadas em `data/reports/saude/raw.json` |
| 2026-09-11 | (pós-processamento, sem nova requisição) | — | 508 -> 386 documentos no corpus final | **2 achados só por leitura manual, nenhum por métrica**: (1) 14 documentos de zootecnia/produção animal passaram pelo filtro de assunto (`nutricao` casa com nutrição animal; `excluir_assunto` só checava área/título/programa, não o resumo); (2) `somente_acesso_aberto` nunca foi aplicado no caminho OAI-PMH (`baixar_por_cota`) — 16 documentos de Acesso Restrito tiveram o PDF baixado e o texto quase publicado | Corrigido: os 30 documentos marcados `no_corpus=false` com motivo em `documentos.parquet`; `excluir_assunto` da UFMG ampliado e passa a checar o resumo; `baixar_por_cota` agora filtra por `extra.direitos` antes de baixar. Curated reconstruída: 386 documentos, ~9,03M palavras |
| | | | | | |

---

## 9. Comunicação com os provedores

| Data | Para | Assunto | Resposta | Arquivo |
|---|---|---|---|---|
| 08/09/2026 | bdtd@ibict.br | orientação sobre coleta acadêmica — decisão em 23/09/2026 | pendente | `docs/correspondencia/` |
| 08/09/2026 | repositório UFPI | aviso prévio + relato de problema de codificação nos metadados OAI | pendente | |
| 08/09/2026 | repositório UFMG | aviso prévio de coleta acadêmica | pendente | |

Avisar o administrador do repositório antes de começar não é obrigatório e não
é exigido pelo OAI-PMH. Mas custa cinco minutos, evita que sua coleta seja
lida como ataque, e o e-mail arquivado é o melhor anexo que esta seção pode
ter.

---

## Anexo A — Modelo de e-mail

> **Assunto:** Coleta acadêmica de metadados via OAI-PMH — UFPI / disciplina DC/CCN072
>
> Prezados,
>
> Sou [nome], aluno(a) de [curso] da Universidade Federal do Piauí. Na
> disciplina Tópicos em Inteligência Artificial (DC/CCN072), sob orientação do
> Prof. Raimundo Santos Moura, estou construindo um corpus de teses e
> dissertações da área de Saúde para experimentos de adaptação de domínio de
> modelos de linguagem em português.
>
> Pretendo colher metadados pelo endpoint OAI-PMH de [repositório] e baixar o
> texto completo apenas dos trabalhos em acesso aberto, com ritmo de uma
> requisição a cada três segundos e User-Agent identificado com meu e-mail.
> Estimo cerca de [N] documentos.
>
> Os PDFs não serão redistribuídos. A publicação prevista se limita a
> metadados, hashes e links de origem, e a eventual subconjunto com licença
> aberta explícita.
>
> Escrevo para (a) avisar previamente, (b) perguntar se há restrição de
> horário ou de volume que eu deva observar, e (c) saber se preferem
> disponibilizar os dados por outro meio.
>
> Fico à disposição e agradeço desde já.
>
> [nome, matrícula, e-mail institucional]

---

## Anexos

- `data/reports/saude/evidencia_*.json` — robots.txt e `Identify` na data da consulta
- `data/reports/saude/inventario.json` — reconciliação, plano amostral e taxonomia declarada
- `data/reports/saude/raw.json` — taxa de resolução por estrato
- `data/reports/saude/processed.json` — reprovações de qualidade, PII removida, duplicatas
- `data/raw/saude/manifesto.jsonl` — ledger completo dos downloads
- `data/curated/saude/DATACARD.md` — composição e limitações do corpus final
- `docs/correspondencia/` — e-mails enviados e respostas recebidas
