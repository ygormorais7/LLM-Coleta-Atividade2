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

Segunda rodada (UFMG, `com_1843_6`, `metadata_prefix=dim`): 508 PDFs baixados,
**386 no corpus final**, ~9,03M palavras. (Rodada anterior, outras fontes:
308 PDFs / 273 aprovados / ~7,3M palavras — números antigos, não somar com os
atuais.)

Correções feitas e validadas contra a rede real nesta rodada: `Crawl-delay`
honrado também na colheita OAI (`ClienteOAI._aplicar_crawl_delay`), UNIFESP
suspensa (violava `Crawl-delay: 15`), `janela_dias` para paginação profunda do
DSpace, `programa` extraído via `metadata_prefix=dim` (o campo real é
`mdschema="local" element="publisher" qualifier="program"`, não
`dc.publisher.program` como documentação teórica sugere — só existe quando a
IES preencheu na origem).

Dois defeitos achados **só lendo o corpus manualmente**, nenhum por métrica
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

Pendente: a janela de datestamp `2026-02-25..2026-06-25` falhou com HTTP 500
persistente durante a colheita de metadado e foi pulada sem retry — número de
registros de Saúde perdidos nessa janela é desconhecido.

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
