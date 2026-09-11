"""
CAMADA STAGING — organização e estruturação.

O que acontece aqui: o JSONL cru vira tabelas relacionais navegáveis, o
encoding dos metadados é acertado, o tipo real de cada arquivo é detectado
pelos magic bytes (e não pela extensão que veio no nome) e a integridade
entre metadado e arquivo é validada.

O que NÃO acontece aqui: nenhuma limpeza de conteúdo, nenhum filtro de
qualidade, nenhuma extração de texto. Estruturar não é filtrar — misturar
as duas coisas é o que torna o pipeline irreprodutível.

Saídas:
  data/staging/<area>/documentos.parquet   1 linha por trabalho
  data/staging/<area>/autores.parquet      1 linha por (doc, autor, papel)
  data/staging/<area>/assuntos.parquet     1 linha por (doc, assunto)
  data/staging/<area>/arquivos.parquet     1 linha por arquivo em disco
  data/reports/<area>/staging.json
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

try:
    import ftfy
except ImportError:  # degradação suave
    ftfy = None

from ..common import Config, Relatorio, configurar_log, doc_id, ler_jsonl

log = configurar_log("staging.organize")

# Assinaturas de arquivo. O SIGAA/repositórios servem PDF com extensão
# errada com uma frequência que surpreende.
ASSINATURAS = [
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip"),        # docx/pptx/xlsx/epub também caem aqui
    (b"\xd0\xcf\x11\xe0", "ole"),  # doc/ppt/xls legados
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpg"),
]

PAPEIS_AUTORIA = {
    "primary": "autor",
    "secondary": "coautor",
    "corporate": "instituicao",
}


def _texto(valor) -> str:
    """Achata qualquer coisa que a API devolva em uma string limpa."""
    if valor is None:
        return ""
    if isinstance(valor, list):
        valor = " ".join(str(v) for v in valor if v)
    valor = str(valor)
    if ftfy:
        valor = ftfy.fix_text(valor)          # conserta mojibake (Ã© -> é)
    valor = unicodedata.normalize("NFC", valor)
    valor = valor.replace("\u2028", " ").replace("\u2029", " ")
    return re.sub(r"\s+", " ", valor).strip()


def _lista(valor) -> list[str]:
    if valor is None:
        return []
    if isinstance(valor, str):
        return [_texto(valor)] if valor.strip() else []
    saida = []
    for item in valor:
        if isinstance(item, list):
            saida.extend(_texto(i) for i in item if i)
        elif item:
            saida.append(_texto(item))
    return [s for s in dict.fromkeys(saida) if s]


_STOPWORDS_PT_RESUMO = {"de","da","do","das","dos","e","o","a","os","as","em","no",
                        "na","para","por","com","que","um","uma","se","ao","como",
                        "foi","ser","não","sobre","entre","pelo","pela","este","esta"}


def _melhor_resumo(valor) -> str:
    """
    Escolhe a versão em PORTUGUÊS entre as descrições do registro.

    O `dc:description` do DSpace costuma trazer resumo e abstract, e a ordem
    varia por repositório. Pegar o primeiro produzia pares de fine-tuning com
    pergunta em português e resposta em inglês — defeito silencioso, porque
    nenhuma métrica de qualidade reprova um texto inglês bem formado.
    """
    candidatos = [c for c in _lista(valor) if len(c) > 120]
    if not candidatos:
        return _texto(valor)

    def escore(texto: str) -> float:
        palavras = re.findall(r"\w+", texto.lower())
        if not palavras:
            return 0.0
        return sum(1 for p in palavras if p in _STOPWORDS_PT_RESUMO) / len(palavras)

    melhor = max(candidatos, key=escore)
    return melhor if escore(melhor) > 0.08 else _texto(candidatos[0])


def _ano(valor) -> int | None:
    for candidato in _lista(valor):
        m = re.search(r"(1[89]\d{2}|20\d{2})", candidato)
        if m:
            return int(m.group(1))
    return None


def _tipo_real(caminho: Path) -> str:
    try:
        with open(caminho, "rb") as fh:
            cabecalho = fh.read(8)
    except OSError:
        return "ilegivel"
    for assinatura, nome in ASSINATURAS:
        if cabecalho.startswith(assinatura):
            return nome
    return "desconhecido"


def _campo_bruto(bruto: dict, *chaves) -> list[str]:
    for chave in chaves:
        if chave in bruto and bruto[chave]:
            return _lista(bruto[chave])
    return []


def montar_tabelas(registros: list[dict], manifesto: list[dict], rel: Relatorio):
    por_doc = {m["doc_id"]: m for m in manifesto}

    docs, autores, assuntos = [], [], []

    for reg in registros:
        ident = reg.get("id") or ""
        did = doc_id(ident)
        bruto = reg.get("rawData") or {}
        man = por_doc.get(did, {})

        docs.append(
            {
                "doc_id": did,
                "id_bdtd": ident,
                "titulo": _texto(reg.get("title") or bruto.get("title")),
                "titulo_alternativo": " | ".join(
                    _campo_bruto(bruto, "title_alt", "dc.title.alternative.fl_str_mv")
                ),
                "resumo": _melhor_resumo(reg.get("summary") or bruto.get("description")),
                "instituicao": _texto(
                    (reg.get("institutions") or [None])[0]
                    or _campo_bruto(bruto, "institution", "dc.publisher.initials.fl_str_mv")
                ),
                "programa": " | ".join(
                    _campo_bruto(bruto, "dc.publisher.program.fl_str_mv", "publisher")
                ),
                "tipo": " | ".join(_lista(reg.get("formats") or bruto.get("format"))),
                "idioma": " | ".join(_lista(reg.get("languages") or bruto.get("language"))),
                "ano": _ano(reg.get("publicationDates") or bruto.get("publishDate")),
                "area_cnpq": " | ".join(_campo_bruto(bruto, "dc.subject.cnpq.fl_str_mv")),
                "direitos": " | ".join(
                    _campo_bruto(bruto, "eu_rights_str_mv", "dc.rights.driver.fl_str_mv")
                ),
                "url_registro": (man.get("urls_origem") or [""])[0],
                "url_pdf": man.get("url_pdf"),
                "arquivo": man.get("arquivo"),
                "sha256_arquivo": man.get("sha256"),
                "bytes_arquivo": man.get("bytes", 0),
                "tem_arquivo": bool(man.get("baixado")),
                "area_projeto": rel.area,
                "staging_em": datetime.now(timezone.utc).isoformat(),
            }
        )

        for papel_api, papel in PAPEIS_AUTORIA.items():
            bloco = (reg.get("authors") or {}).get(papel_api) or {}
            nomes = list(bloco.keys()) if isinstance(bloco, dict) else _lista(bloco)
            for nome in nomes:
                autores.append({"doc_id": did, "nome": _texto(nome), "papel": papel})

        for orientador in _campo_bruto(
            bruto, "dc.contributor.advisor1.fl_str_mv", "dc.contributor.advisor.fl_str_mv"
        ):
            autores.append({"doc_id": did, "nome": orientador, "papel": "orientador"})

        for assunto in _lista(reg.get("subjects")):
            assuntos.append({"doc_id": did, "assunto": assunto})

    df_docs = pd.DataFrame(docs).drop_duplicates(subset=["doc_id"])
    df_autores = pd.DataFrame(autores).drop_duplicates()
    df_assuntos = pd.DataFrame(assuntos).drop_duplicates()

    # Tabela de arquivos: verdade do disco, não do metadado.
    linhas_arquivo = []
    for m in manifesto:
        caminho = m.get("arquivo")
        if not caminho:
            continue
        p = Path(caminho)
        linhas_arquivo.append(
            {
                "doc_id": m["doc_id"],
                "arquivo": str(p),
                "existe": p.exists(),
                "bytes": p.stat().st_size if p.exists() else 0,
                "tipo_declarado": p.suffix.lstrip(".").lower(),
                "tipo_real": _tipo_real(p) if p.exists() else "ausente",
                "sha256": m.get("sha256"),
            }
        )
    df_arquivos = pd.DataFrame(linhas_arquivo)

    return df_docs, df_autores, df_assuntos, df_arquivos


def validar_integridade(df_docs, df_autores, df_assuntos, df_arquivos, rel: Relatorio) -> dict:
    """
    Verificações automáticas. Cada inconsistência vira uma falha tipada no
    relatório, nunca um warning que ninguém lê.
    """
    ids_docs = set(df_docs["doc_id"])
    problemas = {}

    # 1) Arquivo em disco sem metadado correspondente
    orfaos = set(df_arquivos["doc_id"]) - ids_docs if len(df_arquivos) else set()
    for did in orfaos:
        rel.falha(did, "arquivo_orfao", "arquivo sem registro na tabela de documentos")
    problemas["arquivos_orfaos"] = len(orfaos)

    # 2) Metadado que prometeu arquivo e não tem
    if len(df_arquivos):
        ausentes = df_arquivos.loc[~df_arquivos["existe"], "doc_id"].tolist()
    else:
        ausentes = []
    for did in ausentes:
        rel.falha(did, "arquivo_ausente", "manifesto aponta arquivo inexistente")
    problemas["arquivos_ausentes"] = len(ausentes)

    # 3) Chave estrangeira quebrada
    for nome, df in (("autores", df_autores), ("assuntos", df_assuntos)):
        if len(df):
            quebradas = set(df["doc_id"]) - ids_docs
            for did in quebradas:
                rel.falha(did, f"fk_quebrada_{nome}", f"{nome} referencia doc inexistente")
            problemas[f"fk_quebrada_{nome}"] = len(quebradas)

    # 4) Extensão mentindo sobre o conteúdo
    if len(df_arquivos):
        divergentes = df_arquivos[
            (df_arquivos["existe"]) & (df_arquivos["tipo_declarado"] != df_arquivos["tipo_real"])
        ]
        for did, real in zip(divergentes["doc_id"], divergentes["tipo_real"]):
            rel.falha(did, "tipo_divergente", f"conteúdo real: {real}")
        problemas["tipo_divergente"] = len(divergentes)

    # 5) Campos essenciais vazios
    sem_titulo = df_docs[df_docs["titulo"].str.len() == 0]["doc_id"].tolist()
    for did in sem_titulo:
        rel.falha(did, "sem_titulo", "")
    problemas["sem_titulo"] = len(sem_titulo)

    # 6) Duplicata bibliográfica evidente (mesmo título + mesmo ano).
    #    Só é MARCADA aqui; a decisão de remover é da camada Processed.
    if len(df_docs):
        chave = df_docs["titulo"].str.lower().str.strip() + "|" + df_docs["ano"].astype(str)
        problemas["titulos_repetidos"] = int(chave.duplicated().sum())

    return problemas


def executar(cfg: Config) -> Relatorio:
    rel = Relatorio(camada="staging", area=cfg.get_path("projeto.area_rotulo", ""))
    dir_raw = cfg.dir_camada("raw")
    dir_stg = cfg.dir_camada("staging")

    registros = list(ler_jsonl(dir_raw / "metadata" / "registros.jsonl"))
    manifesto = list(ler_jsonl(dir_raw / "manifesto.jsonl"))
    rel.entradas["registros_raw"] = len(registros)
    rel.entradas["itens_manifesto"] = len(manifesto)

    if not registros:
        rel.falha("camada", "raw_vazia", "rode a camada raw antes")
        rel.salvar(cfg.dir_relatorios())
        return rel

    df_docs, df_autores, df_assuntos, df_arquivos = montar_tabelas(registros, manifesto, rel)
    problemas = validar_integridade(df_docs, df_autores, df_assuntos, df_arquivos, rel)

    for nome, df in (
        ("documentos", df_docs),
        ("autores", df_autores),
        ("assuntos", df_assuntos),
        ("arquivos", df_arquivos),
    ):
        destino = dir_stg / f"{nome}.parquet"
        (df if len(df) else pd.DataFrame({"doc_id": []})).to_parquet(destino, index=False)
        rel.saidas[nome] = {"arquivo": str(destino), "linhas": int(len(df))}
        log.info("%s: %d linhas -> %s", nome, len(df), destino.name)

    rel.metricas["validacao"] = problemas
    rel.metricas["com_arquivo"] = int(df_docs["tem_arquivo"].sum())
    rel.metricas["sem_arquivo"] = int((~df_docs["tem_arquivo"]).sum())
    rel.metricas["anos"] = {
        "min": int(df_docs["ano"].min()) if df_docs["ano"].notna().any() else None,
        "max": int(df_docs["ano"].max()) if df_docs["ano"].notna().any() else None,
    }
    rel.metricas["instituicoes_distintas"] = int(df_docs["instituicao"].nunique())

    rel.salvar(cfg.dir_relatorios())
    return rel


if __name__ == "__main__":
    executar(Config.carregar())
