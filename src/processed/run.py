"""
CAMADA PROCESSED — orquestração.

Ordem do pipeline de tratamento (item 3 do enunciado):

  extração  ->  PADRONIZAÇÃO/NORMALIZAÇÃO  ->  ANONIMIZAÇÃO
             ->  repetição interna  ->  QUALIDADE  ->  DEDUPLICAÇÃO

A deduplicação vem por último de propósito: dois documentos só podem ser
comparados depois de normalizados, senão a diferença de encoding faz textos
idênticos parecerem distintos. E a filtragem de qualidade vem antes da
dedup para não gastar MinHash em lixo de OCR.

Saídas:
  data/processed/<area>/texto/<doc_id>.txt          texto tratado e aprovado
  data/processed/<area>/texto_bruto/<doc_id>.txt    saída direta do extrator
  data/processed/<area>/documentos.parquet          métricas por documento
  data/reports/<area>/processed.json
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..common import Config, Relatorio, configurar_log, ler_jsonl, sha256_texto
from ..raw.fontes import _normalizar_nome_coluna, bate_exclusao
from . import dedup as dedup_mod
from .clean import anonimizar, avaliar, normalizar
from .padroniza import padronizar_metadados
from .extract import extrair_lote

log = configurar_log("processed.run")


def _termos_exclusao_escopo(cfg: Config) -> list[str]:
    """
    Reúne `excluir_assunto` de todas as fontes OAI do config (habilitadas ou
    não) num único vocabulário normalizado.

    Existe aqui, e não só na colheita (`raw.fontes.colher_oai`), porque um
    documento baixado numa rodada com um `excluir_assunto` mais frouxo fica
    para sempre em `data/raw/pdf` e `data/processed/texto_bruto` — a
    arquitetura não modifica camada anterior. Reprocessar Processed com a
    lista corrigida é o jeito de aplicar o filtro sem recoletar.
    """
    termos: set[str] = set()
    for fonte in cfg.get_path("inventario.fontes.oai", []) or []:
        termos.update(fonte.get("excluir_assunto", []) or [])
    termos.update(cfg.get_path("inventario.fontes.bdtd_csv.excluir_assunto", []) or [])
    return [_normalizar_nome_coluna(t) for t in termos]


def _expressoes_permitidas_escopo(cfg: Config) -> list[str]:
    return list(cfg.get_path("escopo.expressoes_permitidas", []) or [])


def fora_de_escopo(contexto: str, termos: list[str], permitidas: list[str] | None = None) -> bool:
    return bool(termos) and bate_exclusao(contexto, termos, permitidas)


def executar(cfg: Config) -> Relatorio:
    rel = Relatorio(camada="processed", area=cfg.get_path("projeto.area_rotulo", ""))
    dir_stg = cfg.dir_camada("staging")
    dir_proc = cfg.dir_camada("processed")
    dir_bruto = dir_proc / "texto_bruto"
    dir_limpo = dir_proc / "texto"
    dir_limpo.mkdir(parents=True, exist_ok=True)

    caminho_docs = dir_stg / "documentos.parquet"
    if not caminho_docs.exists():
        rel.falha("camada", "staging_ausente", str(caminho_docs))
        rel.salvar(cfg.dir_relatorios())
        return rel

    df = pd.read_parquet(caminho_docs)
    com_arquivo = df[df["tem_arquivo"] & df["arquivo"].notna()]
    rel.entradas["documentos_staging"] = int(len(df))
    rel.entradas["com_arquivo"] = int(len(com_arquivo))

    # Contexto de escopo por doc (título + programa + resumo + assunto), para
    # reaplicar `excluir_assunto` aqui sem precisar recolher. `area` mora em
    # assuntos.parquet (1 linha por assunto), não em documentos.parquet.
    caminho_assuntos = dir_stg / "assuntos.parquet"
    if caminho_assuntos.exists():
        df_assuntos = pd.read_parquet(caminho_assuntos)
        area_por_doc = (
            df_assuntos.groupby("doc_id")["assunto"].apply(lambda s: " ".join(s)).to_dict()
        )
    else:
        area_por_doc = {}

    termos_exclusao = _termos_exclusao_escopo(cfg)
    permitidas = _expressoes_permitidas_escopo(cfg)

    def _fora_de_escopo(doc_id: str, titulo: str, programa: str, resumo: str) -> bool:
        return fora_de_escopo(
            f"{area_por_doc.get(doc_id, '')} {titulo} {programa} {resumo}", termos_exclusao, permitidas
        )

    metadados_staging = com_arquivo.set_index("doc_id")[["titulo", "programa", "resumo"]]

    # -------------------------------------------------------- ids ATUAIS
    # Só o que está no Staging desta rodada. Sem isto, um PDF/texto_bruto de
    # uma rodada anterior — cujo candidato não voltou na amostra atual porque
    # foi excluído por um `excluir_assunto` mais novo, ou simplesmente não
    # sorteado de novo — fica esquecido em disco e é reprocessado e aprovado
    # de novo aqui, silenciosamente: ele nunca aparece em nenhuma falha, só
    # some depois se por acaso outra camada fizer um inner join que o pegue.
    # Achado real: 12 documentos da 2ª rodada vazaram assim para dentro do
    # `documentos.parquet` da Processed na 3ª rodada.
    ids_atuais = set(com_arquivo["doc_id"])

    # ---------------------------------------------------------- 1. extração
    ja_extraidos = {p.stem for p in dir_bruto.glob("*.txt")} if dir_bruto.exists() else set()
    tarefas = [
        (r.doc_id, r.arquivo)
        for r in com_arquivo.itertuples()
        if r.doc_id not in ja_extraidos
    ]
    resultados = extrair_lote(cfg, tarefas, dir_bruto, rel) if tarefas else []
    rel.metricas["extraidos_nesta_execucao"] = len(resultados)

    # `resultados` só cobre quem foi extraído NESTA execução. Para quem veio
    # do cache de `texto_bruto` (o caso comum numa rodada de reprocessamento),
    # as métricas de extração vêm do histórico persistido por `extrair_lote`
    # — sem isto, `paginas`/`paginas_ocr` zeram pra todo mundo sempre que a
    # extração não precisa rodar de novo.
    caminho_stats = dir_proc / "extracao_stats.jsonl"
    stats_extracao = {r["doc_id"]: r for r in ler_jsonl(caminho_stats)}
    stats_extracao.update({r["doc_id"]: r for r in resultados})

    # -------------------------------------- 2-5. limpeza / anonimização / QA
    cfg_limpeza = cfg.get_path("processed.limpeza", {}) or {}
    cfg_anon = cfg.get_path("processed.anonimizacao", {}) or {}
    cfg_qual = cfg.get_path("processed.qualidade", {}) or {}
    cfg_dedup = cfg.get_path("processed.deduplicacao", {}) or {}

    linhas: list[dict] = []
    textos_aprovados: dict[str, str] = {}
    total_pii = 0
    achados_pii: list[dict] = []

    todos_brutos = sorted(dir_bruto.glob("*.txt")) if dir_bruto.exists() else []
    arquivos_brutos = [p for p in todos_brutos if p.stem in ids_atuais]
    orfaos = len(todos_brutos) - len(arquivos_brutos)
    if orfaos:
        log.info("%d arquivo(s) em texto_bruto ignorado(s): fora do staging "
                  "desta rodada (sobra de rodada anterior)", orfaos)
        rel.metricas["arquivos_brutos_orfaos_ignorados"] = orfaos
    log.info("tratando %d textos extraídos", len(arquivos_brutos))

    for i, caminho in enumerate(arquivos_brutos, 1):
        did = caminho.stem
        texto = caminho.read_text(encoding="utf-8", errors="replace")

        texto = normalizar(texto, cfg_limpeza)

        res_anon = anonimizar(texto, cfg_anon)
        texto = res_anon.texto
        total_pii += res_anon.total
        achados_pii.extend({"doc_id": did, "campo": "texto", **a} for a in res_anon.achados)

        if cfg_dedup.get("remover_linhas_repetidas", True):
            texto, m_rep = dedup_mod.remover_repeticao_interna(
                texto, float(cfg_dedup.get("max_prop_paragrafos_duplicados", 0.30))
            )
        else:
            m_rep = {"paragrafos_removidos": 0, "prop_paragrafos_duplicados": 0.0,
                     "excedeu_limite": False}

        metricas = avaliar(texto, cfg_qual)
        aprovado = metricas["aprovado"] and not m_rep["excedeu_limite"]
        if m_rep["excedeu_limite"]:
            metricas["motivos_reprovacao"].append("repeticao_interna_excessiva")

        if did in metadados_staging.index:
            meta = metadados_staging.loc[did]
            resumo = meta.get("resumo", "")
            # Candidato vindo do inventário da BDTD não traz resumo, e foi pelo
            # resumo que a zootecnia foi pega: sem ele, vale o começo do texto
            # (que, depois do corte de pré-textuais, começa no RESUMO).
            if not isinstance(resumo, str) or not resumo.strip():
                resumo = texto[:3000]
            excluido_por_escopo = _fora_de_escopo(
                did, meta.get("titulo", ""), meta.get("programa", ""), resumo
            )
        else:
            excluido_por_escopo = False
        if excluido_por_escopo:
            aprovado = False
            metricas["motivos_reprovacao"].append("fora_de_escopo_zootecnia")

        ex = stats_extracao.get(did, {})
        linhas.append(
            {
                "doc_id": did,
                "aprovado_qualidade": aprovado,
                "motivos_reprovacao": "|".join(metricas["motivos_reprovacao"]),
                "pii_removida": res_anon.total,
                "pii_detalhe": "|".join(f"{k}:{v}" for k, v in res_anon.ocorrencias.items()),
                "paragrafos_removidos": m_rep["paragrafos_removidos"],
                "paginas": ex.get("paginas", 0),
                "paginas_ocr": ex.get("paginas_ocr", 0),
                "motor_extracao": ex.get("motor", ""),
                "hash_texto": sha256_texto(texto),
                **{k: v for k, v in metricas.items()
                   if k not in ("aprovado", "motivos_reprovacao")},
            }
        )

        if aprovado:
            textos_aprovados[did] = texto
        else:
            rel.falha(did, "reprovado_qualidade", ",".join(metricas["motivos_reprovacao"]))

        if i % 100 == 0:
            log.info("%d/%d tratados", i, len(arquivos_brutos))

    rel.metricas["pii_ocorrencias_removidas"] = total_pii

    # ------------------------------------------------------- 6. deduplicação
    removidos: set[str] = set()
    mapa_dup: dict[str, str] = {}

    if cfg_dedup.get("exata", True):
        r, m = dedup_mod.deduplicar_exato(textos_aprovados)
        removidos |= r
        mapa_dup.update(m)

    restantes = {k: v for k, v in textos_aprovados.items() if k not in removidos}

    if cfg_dedup.get("fuzzy", True):
        r, m = dedup_mod.deduplicar_fuzzy(
            restantes,
            limiar=float(cfg_dedup.get("minhash_limiar_jaccard", 0.80)),
            permutacoes=int(cfg_dedup.get("minhash_permutacoes", 128)),
            shingle_n=int(cfg_dedup.get("shingle_n", 5)),
        )
        removidos |= r
        mapa_dup.update(m)

    for did in removidos:
        rel.falha(did, "duplicata", f"representante={mapa_dup.get(did, '')}")

    finais = {k: v for k, v in textos_aprovados.items() if k not in removidos}
    for did, texto in finais.items():
        (dir_limpo / f"{did}.txt").write_text(texto, encoding="utf-8")

    # ------------------------------------------------------------ 7. saídas
    df_metricas = pd.DataFrame(linhas)
    if len(df_metricas):
        df_metricas["duplicata"] = df_metricas["doc_id"].isin(removidos)
        df_metricas["duplicata_de"] = df_metricas["doc_id"].map(mapa_dup).fillna("")
        df_metricas["no_corpus"] = df_metricas["doc_id"].isin(finais)

    destino = dir_proc / "documentos.parquet"
    (df_metricas if len(df_metricas) else pd.DataFrame({"doc_id": []})).to_parquet(
        destino, index=False
    )

    # Título e resumo vão para SFT e benchmark: passam pela mesma anonimização
    # do corpo do texto, em vez de irem crus da Staging para a Curated.
    pii_metadados = 0
    colunas_meta = ["doc_id", "titulo", "resumo"] + [
        c for c in ("idioma", "tipo", "ano") if c in com_arquivo.columns
    ]
    metadados = padronizar_metadados(com_arquivo[colunas_meta])
    for coluna in ("titulo", "resumo"):
        tratados = []
        for did, valor in zip(metadados["doc_id"], metadados[coluna].fillna("")):
            res_meta = anonimizar(str(valor), cfg_anon)
            pii_metadados += res_meta.total
            achados_pii.extend({"doc_id": did, "campo": coluna, **a} for a in res_meta.achados)
            tratados.append(res_meta.texto)
        metadados[coluna] = tratados
    metadados.to_parquet(dir_proc / "metadados.parquet", index=False)
    rel.saidas["metadados_parquet"] = str(dir_proc / "metadados.parquet")
    rel.metricas["pii_ocorrencias_metadados"] = pii_metadados

    # Cada máscara aplicada, com o trecho em volta já mascarado: é por aqui que
    # se audita falso positivo sem precisar reabrir o texto bruto.
    pd.DataFrame(achados_pii, columns=["doc_id", "campo", "tipo", "contexto"]).to_parquet(
        dir_proc / "pii_relatorio.parquet", index=False
    )
    rel.saidas["pii_relatorio"] = str(dir_proc / "pii_relatorio.parquet")

    rel.saidas["documentos_parquet"] = str(destino)
    rel.saidas["dir_texto"] = str(dir_limpo)
    rel.saidas["documentos_no_corpus"] = len(finais)
    rel.metricas["reprovados_qualidade"] = len(arquivos_brutos) - len(textos_aprovados)
    rel.metricas["duplicatas_removidas"] = len(removidos)
    if len(df_metricas):
        aprov = df_metricas[df_metricas["no_corpus"]]
        media = aprov["palavras"].mean()
        rel.metricas["palavras_totais"] = int(aprov["palavras"].sum())
        rel.metricas["palavras_media"] = 0.0 if pd.isna(media) else round(float(media), 1)
        rel.metricas["paginas_totais"] = int(aprov["paginas"].sum())
        rel.metricas["docs_com_ocr"] = int((aprov["paginas_ocr"] > 0).sum())

    log.info(
        "corpus processado: %d documentos, %s palavras",
        len(finais),
        f"{rel.metricas.get('palavras_totais', 0):,}".replace(",", "."),
    )
    rel.salvar(cfg.dir_relatorios())
    return rel


if __name__ == "__main__":
    executar(Config.carregar())
