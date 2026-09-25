# Atividade Prática 1 — Tokenizador BPE

Implementação dos 5 itens da atividade "Tópicos em IA / PLN: Criação de LLMs
do Zero", usando como corpus base a amostra de teses/dissertações de Saúde já
gerada na camada Curated do projeto (`data/curated/saude/pretreino/`).

## O que o enunciado pede

1. Carregar amostra do dataset, mostrar estatísticas básicas (nº de
   documentos, média de parágrafos e de palavras por documento) e gerar um
   `.txt` único com todos os documentos, separados por delimitador.
2. Tokenizador BPE do GPT-2 (`tiktoken`): confirmar vocabulário de 50.257
   tokens, testar `encode`/`decode`.
3. Pares input-target por janela deslizante, usando `Dataset` e `DataLoader`
   do PyTorch.
4. Camada de token embeddings (`torch.nn.Embedding`), `vocab_size=50257`,
   `output_dim=256`.
5. Embeddings posicionais absolutos, somados aos token embeddings para
   formar os input embeddings.

## Como está implementado (`tokenizador.py`)

| Item | Função | O que faz |
|---|---|---|
| 1 | `carregar_amostra_dataset` | Lê os shards `<split>-*.jsonl` de `pretreino/` (campo `text`, ver `src/curated/build.py:gerar_pretreino` do projeto principal), com amostragem opcional. |
| 1 | `estatisticas_basicas` / `gerar_arquivo_txt` | Calcula as métricas pedidas e escreve o `.txt` com `<|endoftext|>` como delimitador entre documentos (é o token especial nativo do GPT-2, id `50256` — assim o próprio tokenizador já reconhece o corte entre documentos). |
| 2 | `testar_tokenizador_bpe` | `tiktoken.get_encoding("gpt2")`, valida vocabulário, testa "Raimundo Moura" + 3 textos livres. |
| 3 | `DatasetJanelaDeslizante` / `criar_dataloader` | `Dataset` customizado: tokeniza o texto inteiro e desliza uma janela de `max_length` com passo `stride`; o alvo é a entrada deslocada em 1 token (previsão do próximo token). `criar_dataloader` embrulha isso num `DataLoader` (shuffle, batch, drop_last configuráveis). |
| 4 | `criar_token_embeddings` | `nn.Embedding(50257, 256)` com seed fixa (reprodutível). |
| 5 | `criar_positional_embeddings` | Gera a matriz `(max_length, output_dim)` com os valores sequenciais pedidos no enunciado (linha 0 = 1.1, 1.2, 1.3...; linha 1 = 2.1, 2.2...). Depois soma com os token embeddings do lote (broadcast) para formar os input embeddings finais. |

`main()` roda os 5 itens em sequência e imprime os resultados no console.

### Duas decisões de implementação que valem entender

- **Fallback sintético**: se `CAMINHO_PRETREINO` não existir no disco, o
  script gera um corpus sintético pequeno (avisando no console) em vez de
  quebrar. Isso é só para não travar se o caminho estiver errado — os
  resultados que valem pra entrega são os do corpus real.
- **Esquema de embedding posicional**: o enunciado pede valores decimais
  sequenciais (1.1, 1.2, ...) em vez do `nn.Embedding` aprendido que se
  usaria na prática. Isso funciona bem como ilustração didática, mas o
  esquema decimal "estoura" para `output_dim` acima de 9 (a dimensão 9 dá
  `1.10`, que como número de ponto flutuante é igual a `1.1` da dimensão 0)
  — o código tem um comentário sobre essa limitação, caso o professor
  pergunte por que a abordagem "de verdade" seria diferente.

## Como rodar

**Importante:** o script usa um caminho relativo (`data/curated/saude/pretreino`),
então ele precisa ser executado a partir da **raiz do projeto** (onde fica a
pasta `data/`), não de dentro de `atividade1_tokenizador/`.

1. Coloque a pasta `atividade1_tokenizador/` na raiz do seu projeto, ao lado
   de `data/` (onde já está `data/curated/saude/pretreino/`).
2. Abra um terminal **na raiz do projeto** (não dentro de
   `atividade1_tokenizador/`).
3. Instale as dependências:
   ```
   pip install -r atividade1_tokenizador/requirements.txt
   ```
4. Rode:
   ```
   python atividade1_tokenizador/tokenizador.py
   ```

Se preferir não depender de rodar do lugar certo, edite a constante
`CAMINHO_PRETREINO` no topo de `tokenizador.py` para um caminho absoluto,
por exemplo:
```python
CAMINHO_PRETREINO = Path(r"C:\caminho\completo\ate\data\curated\saude\pretreino")
```

### Outros parâmetros ajustáveis (topo do arquivo)

- `SPLIT`: `"treino"`, `"validacao"` ou `"teste"`.
- `N_AMOSTRA`: quantos documentos usar (`None` = todos do split).
- `MAX_LENGTH`, `STRIDE`, `BATCH_SIZE`: parâmetros da janela deslizante — o
  enunciado pede pra testar livremente esses valores.

## O que vai aparecer no console

A saída é dividida em 5 blocos (um por item do enunciado), cada um imprimindo
os números pedidos: estatísticas do dataset, tokens gerados, shape dos lotes
do `DataLoader`, shape dos embeddings, e os primeiros valores da matriz de
embeddings posicionais.

## Nota sobre o enunciado

O PDF diz que `"Raimundo Moura"` deveria gerar os tokens
`[49, 1385, 41204, 49902, 403]`. Rodando de verdade com
`tiktoken.get_encoding("gpt2")`, o último id sai `430`, não `403` — parece
erro de digitação no enunciado (transposição de dígitos): `decode([403])`
dá `"un"`, `decode([430])` dá `"ra"`, e "ra" é o final correto de "Moura". O
script já imprime essa observação automaticamente ao rodar.
