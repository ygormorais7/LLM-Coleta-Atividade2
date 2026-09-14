# Protocolo de Coleta
<!--
> Este documento foi preenchido e datado antes da primeira requisição (versão
> 1.0, 08/09/2026) e é atualizado a cada rodada. O registro de execução (seção 8)
> diz o que de fato aconteceu, incluindo incidentes e decisões de parar.
-->
---

## 0. Identificação

| Campo | Valor |
|---|---|
| Projeto | `bdtd-corpus` — corpus de teses e dissertações da área de Saúde para adaptação de domínio de modelo de linguagem em português brasileiro |
| Grupo | Grupo 7 — Eduardo Melo, Otávio França e Ygor Morais |
| Responsável pela coleta | Grupo 7 |
| E-mail de contato | ygor.morais@ufpi.edu.br |
| Instituição | Universidade Federal do Piauí — Centro de Ciências da Natureza — Departamento de Computação |
| Disciplina | Tópicos em Inteligência Artificial (DC/CCN072), 60h |
| Professor responsável | Prof. Raimundo Santos Moura (rsm@ufpi.edu.br) |
| Programa | SoberanIA |
| Data de início da coleta | 08/09/2026 |
| Versão deste documento | 2.0 (13/09/2026) |

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

**Entrega da disciplina:** o código do pipeline e o relatório (com este
protocolo). **Os dados não são entregues nem publicados.**

### O que NÃO será feito

- **Não haverá redistribuição dos PDFs originais.**
- **Não haverá publicação do texto integral extraído.**
- Não haverá uso comercial.
- Não haverá tentativa de identificar, contatar ou caracterizar indivíduos
  citados nos trabalhos, nem cruzamento com outras bases para esse fim.
- **Não haverá treinamento de modelo a partir do zero.** O volume disponível
  não sustenta isso: a razão compute-ótima do Chinchilla é de cerca de 20 tokens
  por parâmetro, e um corpus de alguns milhares de teses (~100–300 M tokens)
  seria compute-ótimo para um modelo da ordem de 10 M de parâmetros. O uso
  correto é **pré-treino continuado e ajuste fino sobre um modelo aberto já
  existente**, com avaliação de adaptação de domínio.
- Não haverá coleta em massa pela interface de busca da BDTD (seção 3).
- Não haverá coleta de repositório cujo `robots.txt` vete robôs de IA, nem de
  repositório com proteção anti-robô ativa (seção 3).

### Princípio orientador

**Qualidade acima de quantidade**: procedência auditável, amostragem declarada
e perdas medidas valem mais do que uma tentativa malfeita de coletar a área
inteira.

---

## 2. Escopo

| Campo | Valor |
|---|---|
| Área | Saúde |
| Taxonomia declarada no config | `capes.area_avaliacao` (referência de fronteira; a CAPES **não** foi usada como fonte) |
| Definição efetiva de escopo | filtro de assunto sobre área/assuntos, título, programa e resumo: inclusão por lista (radicais no inventário da BDTD) e **exclusão por palavra inteira** de vocabulário de zootecnia/veterinária/agrárias (`config/config.yaml`) |
| Tipos | tese de doutorado, dissertação de mestrado |
| Idioma | português (detecção com limiar de confiança 0,65) |
| Direitos | somente acesso aberto declarado na fonte |
| Recorte temporal | o que a fonte indexa: UFMG com datestamp desde 2019-08 (anos de defesa 2019–2026); inventário da BDTD sem recorte |

### Decisões de fronteira registradas

- **Medicina Veterinária e Zootecnia estão excluídas** (Ciências Agrárias na
  CAPES). A lista de exclusão enumera cada flexão ("bovino", "bovina",
  "bovinos"…): doença animal concorda no feminino ("raiva bovina") e a primeira
  lista, só com plurais masculinos, deixava passar teses de produção animal.
- A exclusão compara **palavra inteira**: por trecho, "equina" casava dentro de
  "catequina" e excluía tese de nutrição.
- **Expressões permitidas** (`escopo.expressoes_permitidas`) são apagadas do
  texto antes da checagem. Revisando à mão os 42 excluídos em 13/09/2026, 10 eram
  de Saúde e caíam por palavra de animal usada em outro sentido: "pé equino"
  (ortopedia infantil), dentina bovina (odontologia in vitro), soro fetal
  bovino, albumina sérica bovina e tripsina bovina (reagentes de laboratório).
- **"Saneamento" não é critério de exclusão**: é tema central de saúde pública.
  Estava na lista para tirar a engenharia sanitária, que continua fora por
  "recursos hídricos".
- **Casos de fronteira mantidos fora:** vaccinia bovina (vírus de gado que
  infecta ordenhadores) e doenças vesiculares de bovinos.
- **Educação Física está incluída** (colégio de Ciências da Saúde na CAPES).
- **Psicologia está excluída** (Ciências Humanas na CAPES).
- O escopo é checado duas vezes: na colheita (sobre o metadado) e de novo na
  Processed (sobre título, programa, resumo e, quando não há resumo, o começo do
  texto), para que uma lista corrigida valha para o que já foi baixado sem
  recolher.

---

## 3. Fontes

A evidência de cada fonte é um JSON em `data/reports/saude/` com o `robots.txt`
**como estava na data da consulta**:
`evidencia_<base>.json` (comando `descobrir`, com `Identify` do OAI) ou
`evidencia_robots_<dominio>.json` (comando `robots`, só o `robots.txt`).
O `preflight.py` bloqueia a coleta se faltar evidência de algum domínio.

| # | Fonte | Endpoint / origem | Protocolo | Verificado em | Situação |
|---|---|---|---|---|---|
| 1 | Repositório Institucional da UFMG, set `com_1843_6` | `https://repositorio.ufmg.br/server/oai/request` | OAI-PMH (`dim` + ORE) | 08/09/2026 | **fonte principal** |
| 2 | Inventário da BDTD montado pelo grupo | `data/externo/inventario_saude.csv.gz` → página do item no repositório de origem | arquivo local + HTTP no repositório | 13/09/2026 | piloto (UFRN, UFPR, Fiocruz); **coleta até 20 mil PDFs autorizada em 13/09/2026** (até 800 candidatos por instituição) |
| 3 | Repositório Institucional da UFPI | `https://repositorio.ufpi.br/oai/request` | OAI-PMH | 08/09/2026 | não usada nesta entrega |
| 4 | UNIFESP (três unidades de Saúde) | `https://repositorio.unifesp.br/oai/request` | OAI-PMH | 08/09/2026 | **suspensa**: `Crawl-delay: 15` violado por versão antiga do coletor; depois, conexão recusada |
| 5 | ARCA/Fiocruz via OAI | endpoint OAI não localizado | — | 08/09/2026 | substituída pelo acesso às páginas de item via fonte 2 |
| 6 | Catálogo CAPES | dadosabertos.capes.gov.br | dados abertos | — | não usada |

### Sobre a fonte 2 (inventário da BDTD do grupo)

O grupo montou o inventário da área pela **API REST** da BDTD
(`/vufind/api/v1/search`), fatiando a consulta por prefixo de identificador:
183.718 fichas (título, autor, ano, tipo, instituição, direitos e a URL do item
no repositório de origem). O `robots.txt` da BDTD proíbe só `/vufind/Search/`
(a busca da interface); a API é a porta feita para programas. **Reutilizar o
arquivo pronto não gera nenhuma requisição nova à BDTD.**

Sobre esse inventário aplicamos os filtros deste projeto: acesso aberto com URL,
escopo de Saúde (radicais testados: "medic" sozinho casa com "medição" e
"hospital" com "hospitalidade", por isso não são usados), exclusão de
zootecnia e exclusão de instituições (seção abaixo). O arquivo não traz resumo;
o escopo é checado de novo na Processed com o começo do texto.

### Evidência de `robots.txt` dos domínios do piloto (13/09/2026)

| Domínio | O que o `robots.txt` diz | Decisão |
|---|---|---|
| `hdl.handle.net` | `User-agent: *` / `Crawl-delay: 1` | coleta permitida; nosso intervalo (3 s) é maior. O repositório final de cada handle tem o `robots.txt` checado ao vivo a cada redirecionamento |
| `repositorio.ufrn.br` | lista padrão do DSpace: bloqueia `/search`, `/admin`, `/submit`… e robôs de cópia em massa; nenhum robô de IA | coleta permitida. A API REST `/server/api` (usada porque a página do item vem sem link) não é bloqueada, e cada chamada passa pelo mesmo `robots.txt` e ritmo |
| `arca.fiocruz.br` | idem (DSpace 7) | coleta permitida |
| `hdl.handle.net` → UFPR (prefixo `1884`) | — | **retirada** após o piloto 2: o servidor de handles da UFPR responde HTTP 500 ("Cannot Connect to Server") |
| `tede2.pucrs.br` | `User-agent: * Allow: /`, mas **proíbe nominalmente robôs de IA**: GPTBot, ClaudeBot, CCBot, Google-Extended, Amazonbot, Applebot-Extended, Bytespider, meta-externalagent | **excluída**: a letra deixaria nosso User-Agent passar, mas o espírito é não ceder conteúdo para treino de modelo, que é o uso deste corpus |
| `repositorio.ufsc.br` | `/robots.txt` devolve **página de desafio anti-robô do Cloudflare** (Turnstile), não um robots.txt | **excluída**: sem regra legível e com proteção ativa contra acesso automatizado |
| `repositorio.ufmg.br` (08/09) | lista padrão do DSpace; nenhum robô de IA | fonte principal |

### Evidência de `robots.txt` para a coleta até 20 mil (13/09/2026, 13:26–13:50)

Uma requisição por domínio (`python -m src.raw.inventario robots`), mais **uma**
nova tentativa só para falhas que podiam ser passageiras (tempo esgotado,
resposta malformada): 23 domínios, dos quais nenhum voltou. Classificação
automática (`src/raw/robots.py`) de 179 domínios (esquema + endereço) e 35.238
candidatos (até 800 por instituição):

| Veredito | Domínios | Candidatos | Decisão | Maiores |
|---|---:|---:|---|---|
| `ok` (regras lidas, nosso agente autorizado) | 79 | 17.366 | **fica** | hdl.handle.net, UFU, UFRN, UFPA, UEL |
| sem robots.txt (HTTP 404) | 20 | 3.084 | **fica** | UEM, UFMA, UCPel |
| página HTML no lugar do robots.txt, sem desafio | 3 | 803 | **fica** | UECE |
| inacessível (tempo esgotado 16, certificado TLS inválido 9, DNS 6, resposta malformada 4, conexão recusada 3, outros 3) | 39 | 6.495 | sai | UERJ, UFTM, UFJF, UNIFAL, UFAM |
| HTTP 403 | 12 | 2.732 | sai (bloqueio) | UFPE, UFSM, Cruzeiro do Sul |
| **veto nominal a robôs de IA** | 10 | 2.641 | sai (espírito) | UFPB (CCBot), UFPel (GPTBot, CCBot), PUC Goiás, Sophia, UFFS (GPTBot, Claude-Web), UNISA, Metodista |
| HTTP 468 (bloqueio de firewall) | 4 | 1.306 | sai | PUC-SP, UFBA |
| HTTP 503 / 522 / 500 | 6 | 578 | sai (servidor com problema) | UnB, Bahiana |
| `Disallow: /` para todos | 3 | 187 | sai | Franciscana, LNCC, ESPM |
| **desafio anti-robô** (Cloudflare) | 3 | 46 | sai | Unicesumar, Uninter, Anhembi |
| **Total** | **179** | **35.238** | fica 21.253 · sai 13.985 | |

Certificado TLS inválido não é contornado: a verificação nunca é desligada. Os
vetos a robôs de IA foram conferidos à mão: cada domínio tem um grupo explícito
(`User-agent: CCBot` / `GPTBot` / `ClaudeBot`… com `Disallow: /`), às vezes
abaixo das regras padrão do DSpace. Links `hdl.handle.net` (3.582 candidatos)
têm o robots.txt do domínio final classificado ao vivo, com as mesmas regras.
Evidência: `data/reports/saude/evidencia_robots_*.json` (conteúdo inteiro e
veredito).

### O que foi deliberadamente evitado

Coleta em massa pela interface de busca da BDTD. O `robots.txt` do portal
contém `Disallow: /vufind/Search/`. Consultas pontuais ao portal, quando
necessárias para validação manual, são feitas por navegador, por uma pessoa.

`robots.txt` (https://bdtd.ibict.br/robots.txt) no dia do início da coleta:

```
User-agent: *
Allow: /
Disallow: /vufind/Search/
```

**Regra geral adotada:** quando a letra e o espírito de um `robots.txt`
divergem, vale o espírito (BDTD, PUC-RS).

---

## 4. Conduta técnica

| Parâmetro | Valor adotado | Onde está configurado |
|---|---|---|
| User-Agent | `bdtd-corpus/1.0 (pesquisa academica; UFPI; +mailto:ygor.morais@ufpi.edu.br) python-requests` | `src/common.py::Config.user_agent` |
| robots.txt | consultado e respeitado por domínio, inclusive o `Crawl-delay`, em **todos** os caminhos de rede (colheita OAI e download) | `coleta.http.respeitar_robots: true`; `ClienteOAI._aplicar_crawl_delay`; `ResolvedorTextoCompleto._permitido` |
| Ritmo na fonte de metadados | 1 requisição a cada 2 s | `requisicoes_por_segundo: 0.5` |
| Ritmo por domínio de repositório | 1 requisição a cada 3 s (ou o `Crawl-delay`, se maior) | `rps_repositorios: 0.33` |
| Paralelismo | até 24 **instituições** em paralelo, em rodadas de 200 candidatos cada; **dentro de um domínio o intervalo é sempre o do config** (o limitador reserva o próximo horário livre por domínio) | `coleta.max_instituicoes_paralelas`, `coleta.rodada_por_instituicao`, `RateLimiter.aguardar` |
| Redirecionamento | seguido à mão; cada salto passa pelo `robots.txt` e pelo ritmo do domínio de destino (link `hdl.handle.net` → repositório final) | `ResolvedorTextoCompleto._obter` |
| Retry | backoff exponencial; `Retry-After` respeitado; `503` do OAI tratado como controle de fluxo | `bdtd_client.py`, `fontes.py` |
| Janela OAI que falha | dividida ao meio até 1 dia; o que não se recupera é **declarado** no relatório | `ClienteOAI._colher_janela` |
| **Disjuntor** | **5 falhas seguidas sem registro novo interrompem a colheita** e declaram o resto do intervalo como perdido | `ClienteOAI.FALHAS_SEGUIDAS_MAX` |
| **Disjuntor por instituição (download)** | depois de 20 tentativas, instituição com **erro acima de 30%** sai da coleta sozinha e vai para o relatório (`instituicoes_interrompidas`) — o critério de parada da seção abaixo, sem depender de alguém olhando | `coleta.disjuntor`, `harvest.baixar_por_cota` |
| Tamanho máximo por arquivo | 120 MB | `tamanho_max_pdf_mb` |
| Conteúdo | só grava se começar com `%PDF`; página de login/erro com HTTP 200 é descartada | `ResolvedorTextoCompleto.baixar` |
| ORE quando disponível | sim: o OAI entrega a URL do arquivo e dispensa a requisição à página HTML | `prefix_binarios: "ore"` |
| **robots.txt pelo espírito, automático** | cada domínio é classificado: **veto nominal a robôs de IA** (GPTBot, ClaudeBot, CCBot…), **página de desafio anti-robô**, bloqueio total ao nosso agente, HTTP 401/403/429/5xx ou inacessível → domínio **fora da coleta**. Vale na evidência (sai do inventário; o preflight bloqueia se sobrar), e ao vivo no domínio final de cada link `hdl.handle.net` | `src/raw/robots.py`, `inventario.vereditos_robots`, `ResolvedorTextoCompleto._carregar_robots` |
| Página do item sem link (DSpace 7) | a API REST do próprio repositório (`/server/api`: item → pacote `ORIGINAL` → PDF), só depois de a página não trazer metatag nem link; metatag com endereço interno (`localhost`) é trocada pelo domínio da página | `ResolvedorTextoCompleto._descobrir_dspace7`, `_no_mesmo_site` |
| Meta de PDFs | `coleta.meta_pdfs` (0 = sem meta) | `harvest.baixar_por_cota` |
| Antes de qualquer coleta | `python -m pytest` e `python preflight.py` (bloqueia sem contato, sem evidência de robots.txt por domínio, com ritmo acima do protocolo) | `preflight.py` |

### Janela de coleta

Madrugada ou fim de semana, fora do horário de maior uso dos repositórios.

### Critérios de parada imediata

A coleta é interrompida, e o incidente registrado na seção 8, se ocorrer:

- HTTP 429, 500 ou 503 persistente em um mesmo domínio (no OAI, o disjuntor
  aplica isso sozinho após 5 falhas seguidas);
- bloqueio por IP ou por User-Agent, ou página de desafio anti-robô;
- **qualquer contato de administrador de repositório** — resposta no mesmo dia e
  suspensão até acordo;
- sinal de degradação do serviço (tempo de resposta subindo consistentemente);
- taxa de erro acima de 30% em um domínio.

---

## 5. Dados pessoais (LGPD)

### Enquadramento

Tratamento para fins exclusivamente acadêmicos, por instituição de ensino e
pesquisa, sem identificação de titulares e sem qualquer decisão que os afete.
Dispositivos pertinentes da Lei 13.709/2018: Art. 4º, II, 'b' (finalidade
acadêmica), Art. 7º, IV (estudos por órgão de pesquisa, garantida sempre que
possível a anonimização), Art. 5º, II (dado sensível, que inclui dado referente à
saúde) e Art. 11 (tratamento de dados sensíveis).

### Comitê de ética em pesquisa

A Resolução CNS 510/2016 lista, entre as pesquisas que não são registradas nem
avaliadas pelo sistema CEP/CONEP, as que utilizam informações de acesso público
ou de domínio público. Teses e dissertações depositadas em repositório
institucional aberto se enquadram nessa descrição, e não há contato com
participantes de pesquisa nem acesso a dados não publicados.

### Política de anonimização

**Autoria não é anonimizada.** Autor, orientador e instituição são metadados
bibliográficos públicos; removê-los destruiria a proveniência sem ganho de
privacidade. **O alvo é PII de terceiros no corpo do texto** e também no título
e no resumo que vão para o SFT e o benchmark.

| Medida | Situação |
|---|---|
| Corte de pré-textuais, incluindo agradecimentos | implementado (`cortar_pretextuais`) |
| Corte de anexos e apêndices | ligado (`cortar_pos_referencias: true`) — não pega todas as folhas de assinatura: CPFs reais de TCLE foram achados e mascarados |
| CPF, CNPJ, **título de eleitor, PIS/PASEP e cartão SUS com dígito verificador** | implementado |
| Telefone com DDD válido, CEP, RG (7 a 10 dígitos), e-mail, perfil de rede social | implementado |
| **Links, DOI e ORCID fora dos detectores numéricos** | implementado (seus dígitos imitavam documento) |
| Placa de veículo | **desligada** (colidia com nome de gene e sigla de estudo) |
| Título e resumo anonimizados antes do SFT/benchmark | implementado (`metadados.parquet`) |
| Relatório de cada máscara, com o contexto já mascarado | `data/processed/saude/pii_relatorio.parquet` |
| **Verificação final do Curated, que para o pipeline com erro** | `src/curated/verificar_pii.py`, rodado pelo `run_pipeline.py` |
| NER de nomes de pessoa | desligado — ver justificativa |
| Auditoria manual de amostra | feita a cada rodada (seção 8) |
| Recall medido em amostra rotulada | **não medido** (trabalho futuro). A leitura do relatório de PII já mostrou formatos que escapam, como telefone sem hífen `(31) 3xxxxxxx` e DDD escrito `(0XX31)` |

**Por que o NER de nomes fica desligado.** Texto acadêmico é denso em nomes
próprios legítimos ("segundo Minayo (2014)", "a técnica de Bardin", nomes de
escalas e síndromes). Um NER de pessoas mascararia todos eles. A maior
concentração de nomes de terceiros fica nos agradecimentos e nos anexos, já
cortados.

**Precisão antes de recall, com medição.** Em 13/09/2026 recuperamos o valor por
trás de cada máscara: ~1.900 eram falsas (DOI virando PIS/cartão SUS, ORCID
virando título de eleitor, gene `CYP2C19` e sigla `OMS-2008` virando placa). Os
detectores foram corrigidos e o diagnóstico refeito sobre as 2.840 teses (ver
relatório da atividade).

### Limitação declarada: quase-identificadores

A combinação de idade, doença rara, município e ano permite reidentificação sem
que nenhum CPF ou nome apareça. **Nenhum regex, NER ou detector de PII resolve
isso.** O corpus **não é declarado anonimizado**: declara-se o que foi detectado
e mascarado, e este risco residual como conhecido e não mitigado por meios
automáticos.

---

## 6. Direitos autorais

Cada tese tem licença própria, definida pela instituição de defesa e pelo
autor. O texto extraído é obra derivada: a licença governa publicá-lo tanto
quanto publicar o PDF. **Acesso aberto não é licença de redistribuição.**

| Produto | Política |
|---|---|
| PDF original | não redistribuído; permanece em disco local |
| Texto integral extraído | uso interno acadêmico, restrito à disciplina |
| Metadados + `sha256` + link de origem | publicável |
| Subconjunto com licença aberta explícita (Creative Commons) | publicável em tese; não publicado nesta entrega |

---

## 7. Retenção e descarte

| Item | Onde | Versionado no Git | Retenção | Descarte |
|---|---|---|---|---|
| PDFs originais | `data/raw/saude/pdf/` | não (`.gitignore`) | até o fim do semestre letivo | exclusão do diretório |
| Texto extraído e tratado | `data/processed/saude/` | não | idem | idem |
| Inventário, manifesto e inventário do grupo | `data/raw/saude/*.jsonl`, `data/externo/` | não | idem | idem |
| Relatórios de camada e evidências de robots.txt | `data/reports/saude/*.json` | **sim** | permanente | — |
| DATACARD e este protocolo | `data/curated/saude/DATACARD.md`, `docs/` | **sim** | permanente | — |

Os relatórios, as evidências e o DATACARD ficam versionados porque são a prova
de auditoria: sem eles não há como responder por que um documento entrou ou saiu
do corpus.

---

## 8. Registro de execução

| Data | Fonte | Requisições | Documentos obtidos | Incidentes | Observações |
|---|---|---|---|---|---|
| 2026-09-10/11 | UFMG (`com_1843_6`, dim) — 2ª rodada | metadado: ~38.638 registros do set; ORE nos sorteados; PDF: ~520 tentativas | 508 PDFs → 386 documentos no corpus | 1 janela de datestamp (`2026-02-25..2026-06-25`) com HTTP 500 persistente, pulada sem retry | amostra `n_alvo=500`; 2 defeitos achados só por leitura manual (zootecnia no corpus; `somente_acesso_aberto` não aplicado no caminho OAI) |
| 2026-09-11/12 | UFMG (`com_1843_6`, dim) — 3ª rodada | metadado: 38.638 registros → 3.632 candidatos; ORE: 3.632; PDF: ~3.460 tentativas | **3.474 PDFs** (185 bloqueados por direitos) | a mesma janela de datestamp falhou de novo | `n_alvo=5000` (set inteiro); rodou em tmux e sobreviveu à suspensão da máquina |
| 2026-09-12/13 | (pós-processamento, sem requisição) | — | 2.873 → 2.840 no corpus final | **auditoria manual**: zootecnia no corpus (flexão no feminino), ~1.900 máscaras de PII falsas, arquivo órfão de rodada anterior reaprovado, métrica de página zerando com cache, RAG estourando memória, exclusão por trecho de palavra ("equina" em "catequina") | corrigidos e cobertos por testes (`python -m pytest`) |
| 2026-09-13 04:12 | UFMG — recoleta da janela `2026-02-25..2026-06-25` (dim) | 15 com falha | 0 | **HTTP 500 em todo recorte, até 1 dia.** Interrompida manualmente pelo critério de parada. Deu origem ao disjuntor | — |
| 2026-09-13 04:17 | UFMG — diagnóstico da janela | ~10 | — | nenhum | `ListIdentifiers` conta **755 registros** (+2 excluídos) na janela; `oai_dc` responde a 1ª página. Evidência: `data/reports/saude/diagnostico_janela_ufmg.json` |
| 2026-09-13 04:23 | UFMG — recoleta da janela em `oai_dc` | ~15 | 235 registros → 13 de Saúde → **4 candidatos novos** | a paginação em `oai_dc` também dá 500; **o disjuntor interrompeu sozinho** após 5 falhas | ~520 registros seguem não colhidos (~50 de Saúde, estimado), declarados em `inventario_janela.json` |
| 2026-09-13 04:23 | Inventário BDTD — piloto 1 (UFSC, UFRN, PUC-RS, UFPR, Fiocruz) | robots.txt: 8; download: poucas antes da interrupção | **0 PDFs** | PUC-RS veta robôs de IA no robots.txt; UFSC responde com desafio anti-robô do Cloudflare. **Download interrompido** antes de gravar qualquer arquivo | as duas instituições foram excluídas; o inventário foi restaurado sem elas |
| 2026-09-13 04:27 | Inventário BDTD — piloto 2 (UFRN, UFPR, Fiocruz; 60 cada) + 4 da janela UFMG | 180 candidatos, ~2 a 3 por candidato | **0 de 180 PDFs** (UFMG: +3 da janela) | **taxa de erro de 100% nos três domínios** → critério de parada: expansão não seguiu | testes e preflight antes (106 testes; 0 bloqueios). Falhas: UFRN e UFPR `pdf_nao_localizado` (60 cada), Fiocruz `bloqueado_ou_erro_rede` (60). Relatório preservado em `raw_piloto2.json` |
| 2026-09-13 04:42 | Diagnóstico do piloto 2 (1 registro por instituição, sem baixar PDF) | ~15 | — | nenhum | UFRN: DSpace 7 sem renderização no servidor, página de 1 KB sem link; a API REST `/server/api` chega ao PDF. Fiocruz: `citation_pdf_url` aponta para `http://localhost:4000/...` (configuração do servidor deles). UFPR: `hdl.handle.net/1884/...` responde "Cannot Connect to Server" (HTTP 500) — servidor de handles da UFPR fora do ar. Evidência: `diagnostico_piloto_bdtd.json` |
| 2026-09-13 04:47 | Inventário BDTD — piloto 3: **os mesmos 120 candidatos** de UFRN e Fiocruz, depois de corrigir o coletor | ~5 por candidato na UFRN (página + API REST), ~2 na Fiocruz; 04:47–05:09 | **119 de 120 PDFs** (UFRN 60/60, Fiocruz 59/60; 473 MB) | nenhum (1 `pdf_nao_localizado` na Fiocruz) | UFPR retirada (serviço falhando). Nenhum candidato novo. 109 testes; preflight com 0 bloqueios |
| 2026-09-13 05:09–07:05 | (pós-processamento, sem requisição) | — | **2.951 no corpus final** (UFMG 2.845, Fiocruz 54, UFRN 52); 72,0 M palavras | a verificação de PII do Curated **parou o pipeline** numa passada intermediária (telefone quebrado em linha escapando); leitura manual achou pares de SFT com abstract e 10 teses de Saúde excluídas como zootecnia | todos corrigidos e cobertos por teste (128); verificação final: **0 ocorrências** |
| 2026-09-13 13:26– | Inventário BDTD — **coleta até 20 mil PDFs** (141 instituições, 159 domínios; até 800 candidatos sorteados por instituição; UFPR, UFMG, UNIFESP, PUC-RS e UFSC fora) | 1) robots.txt de cada domínio; 2) inventário sem domínios vetados; 3) download em 4 execuções (abaixo) | **15.098 PDFs no disco ao fim**, com a meta reduzida para 15 mil pelo prazo de entrega | ver as execuções abaixo | 145 testes; preflight antes de cada etapa; disjuntor por instituição ativo |
| 2026-09-13 13:51–14:40 | Coleta até 20 mil — download, 1ª execução | 6.000 tentativas (~84% de sucesso) | **8.748 PDFs no disco** (de 3.596) | **o disjuntor cortou 26 instituições** (8.858 candidatos, 41% do inventário BDTD), quase todas com 0 de 20 | diagnóstico com 1 link por instituição cortada e uma sonda de ~10 requisições nos DSpace 7 (`diagnostico_coleta20k_cortadas.json`): 19 falhas **legítimas** (certificado TLS inválido na UFRGS e na UFJF; handle fora do ar na UFT; prefixo de handle inexistente na UNIRIO; robots.txt 503 na UNICAMP e veto a robôs de IA na Univates, ambos no domínio final; página "você não é um bot" na FGV e na UNISINOS; HTTP 403, 404 ou 500; conexão recusada ou derrubada) e 3 sistemas não reconhecidos (Tainacan, JSF, Kroton) → **suspensas no config, sem nenhuma requisição**; 7 **defeitos do coletor**, corrigidos com teste (155): API do DSpace 7 declarada em `assets/config.json` (IEC, UDESC, UFG), handle não numérico, `/bitstreams/…/download` que devolve HTML (UFG, UFMS, Mackenzie), metatag com IP e porta 4000 (UEPB), barra dupla no link (UEG), desafio anti-robô na página tira o domínio na 1ª vez |
| 2026-09-13 14:40–17:15 | Coleta até 20 mil — download, 2ª execução, com as correções (processo anterior encerrado de propósito; manifesto gravado item a item e copiado antes) | ~6.000 tentativas | **14.488 PDFs no disco** | 11 instituições cortadas pelo disjuntor, parte delas por corte falso na retomada (ver 17:15) | encerrada de propósito: **meta reduzida para 15 mil pelo prazo de entrega** |
| 2026-09-13 17:15–17:28 | 3ª execução, meta 15 mil | ~450 tentativas | 14.551 | **defeito do disjuntor na retomada**: os PDFs já obtidos eram pulados sem contar, e instituições boas (UEM, UFMA, UFES) caíram com "0 de 20" só em falhas antigas | encerrada para corrigir (o disjuntor parte do histórico; 156 testes); IEC, UEG, UFRRJ e Mackenzie suspensas (correções não bastaram, robots.txt 403 ou 404) |
| 2026-09-13 17:28–17:45 | 4ª execução, meta 15 mil, disjuntor com histórico | ~800 tentativas | **15.098 PDFs no disco: meta atingida** (UFMG 3.477, piloto 119, coleta em escala 11.502; 62 instituições) | disjuntor cortou UDESC (15 de 22) e UFMS (25 de 36) pela taxa real; desafio anti-robô visto ao vivo em repositorio.ufersa.edu.br e saberaberto.uneb.br (domínios saíram na hora) | 23 instituições suspensas, sem nenhuma requisição; testes e preflight antes |
| 2026-09-13 18:53–20:05 | (pós-processamento, sem requisição) — amostra de 5.023 PDFs: os 3.582 já tratados + até 40 sorteados por instituição entre os novos | — | **4.219 no corpus** (62 instituições), 98,8 M palavras; 6.555 dados pessoais mascarados | leitura manual: ~7 das 18 exclusões por escopo em documentos sem resumo eram de Saúde (sobrenome "Bezerra", "recursos hídricos" em estudo de dengue) — declarado como limitação | verificação de PII no Curated: **0 ocorrências**; 157 testes |

---

## 9. Comunicação com os provedores

| Data | Para | Assunto | Resposta | Arquivo |
|---|---|---|---|---|
| 08/09/2026 | bdtd@ibict.br | orientação sobre coleta acadêmica | pendente | `docs/correspondencia/` |
| 08/09/2026 | repositório UFPI | aviso prévio + relato de problema de codificação nos metadados OAI | pendente | |
| 08/09/2026 | repositório UFMG | aviso prévio de coleta acadêmica | pendente | |

Avisar o administrador do repositório antes de começar não é obrigatório e não
é exigido pelo OAI-PMH, mas evita que a coleta seja lida como ataque. Sugestão
para a UFMG: relatar o HTTP 500 no OAI para registros com datestamp entre
2026-02-25 e 2026-06-25, com os endereços exatos que falharam
(`data/reports/saude/inventario_janela.json`).

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
> metadados, hashes e links de origem.
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

- `data/reports/saude/evidencia_*.json` e `evidencia_robots_*.json` — robots.txt na data da consulta
- `data/reports/saude/inventario.json`, `inventario_janela.json`, `inventario_bdtd.json` — inventário, janela recuperada e piloto
- `data/reports/saude/diagnostico_janela_ufmg.json` — diagnóstico do incidente da janela
- `data/reports/saude/raw.json` — taxa de resolução por estrato
- `data/reports/saude/processed.json` — reprovações, PII removida, duplicatas, arquivos órfãos
- `data/reports/saude/verificacao_pii_curated.json` — verificação final do Curated
- `data/raw/saude/manifesto.jsonl` — ledger completo dos downloads
- `data/curated/saude/DATACARD.md` — composição e limitações do corpus final
- `docs/correspondencia/` — e-mails enviados e respostas recebidas
