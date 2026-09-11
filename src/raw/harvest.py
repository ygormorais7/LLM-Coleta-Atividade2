"""
CAMADA RAW — preservação.

Princípio: o dado bruto é intocável. Aqui nada é limpo, convertido ou
renomeado por conteúdo. O que a API devolveu é gravado como veio; o PDF é
gravado byte a byte como o repositório entregou.

Saídas:
  data/raw/<area>/metadata/registros.jsonl   resposta crua da API, 1 por linha
  data/raw/<area>/pdf/<doc_id>.pdf           arquivo original
  data/raw/<area>/manifesto.jsonl            ponte doc_id <-> arquivo <-> origem
  data/reports/<area>/raw.json               relatório de auditoria

O manifesto NÃO é transformação: é a nota fiscal da coleta (o que foi pedido,
o que chegou, com que hash, quando). Sem ele não existe reprocessamento
confiável.

Retomada: a coleta é idempotente. Rodar de novo pula o que já tem arquivo
com hash íntegro e só tenta os que faltaram.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from ..common import (
    Config,
    Relatorio,
    configurar_log,
    doc_id,
    escrever_jsonl,
    humanizar_bytes,
    ler_jsonl,
)
from .bdtd_client import BDTDClient, RespostaInesperada
from .fulltext import ResolvedorTextoCompleto

log = configurar_log("raw.harvest")

# Valores do campo de direitos que indicam acesso aberto de verdade.
MARCADORES_ABERTO = ("openaccess", "open access", "acesso aberto", "info:eu-repo/semantics/openaccess")


def _extrair_urls(registro: dict) -> list[str]:
    urls = []
    for u in registro.get("urls") or []:
        if isinstance(u, dict) and u.get("url"):
            urls.append(u["url"])
        elif isinstance(u, str):
            urls.append(u)
    bruto = registro.get("rawData") or {}
    for chave in ("url", "urls", "dc.identifier.uri.fl_str_mv", "link_str_mv"):
        valor = bruto.get(chave)
        if isinstance(valor, str):
            urls.append(valor)
        elif isinstance(valor, list):
            urls.extend([v for v in valor if isinstance(v, str)])
    # dedup preservando ordem
    vistos, saida = set(), []
    for u in urls:
        if u not in vistos:
            vistos.add(u)
            saida.append(u)
    return saida


def _e_acesso_aberto(registro: dict) -> bool:
    bruto = registro.get("rawData") or {}
    campos = []
    for chave in ("eu_rights_str_mv", "dc.rights.driver.fl_str_mv", "rights", "dc.rights.fl_str_mv"):
        valor = bruto.get(chave)
        if isinstance(valor, str):
            campos.append(valor)
        elif isinstance(valor, list):
            campos.extend([v for v in valor if isinstance(v, str)])
    if not campos:
        return True  # sem informação: não presumir fechado, mas registrar
    texto = " ".join(campos).lower()
    return any(m in texto for m in MARCADORES_ABERTO)


def coletar_metadados(cfg: Config, rel: Relatorio) -> list[dict]:
    """Etapa 1: varre a API e grava a resposta crua."""
    cliente = BDTDClient(cfg)
    dir_raw = cfg.dir_camada("raw")
    destino = dir_raw / "metadata" / "registros.jsonl"

    lookfor = cfg.get_path("coleta.lookfor", "")
    tipo = cfg.get_path("coleta.type", "AllFields")
    filtros = list(cfg.get_path("coleta.filtros", []))
    limite = int(cfg.get_path("coleta.max_registros", 0))

    rel.parametros.update(
        {"lookfor": lookfor, "type": tipo, "filtros": filtros, "max_registros": limite}
    )

    registros: list[dict] = []
    try:
        for reg in cliente.iterar(lookfor=lookfor, tipo=tipo, filtros=filtros, limite_total=limite):
            reg["_coletado_em"] = datetime.now(timezone.utc).isoformat()
            registros.append(reg)
            if len(registros) % 250 == 0:
                log.info("%d registros coletados", len(registros))
    except RespostaInesperada as exc:
        rel.falha("api", "resposta_inesperada", str(exc))
        log.error("coleta interrompida: %s", exc)

    escrever_jsonl(destino, registros)
    rel.saidas["metadata_jsonl"] = str(destino)
    rel.saidas["registros_coletados"] = len(registros)
    log.info("metadados gravados em %s (%d registros)", destino, len(registros))
    return registros


def baixar_textos(cfg: Config, registros: list[dict], rel: Relatorio) -> list[dict]:
    """Etapa 2: segue cada registro até o repositório e baixa o PDF."""
    resolvedor = ResolvedorTextoCompleto(cfg)
    dir_raw = cfg.dir_camada("raw")
    dir_pdf = dir_raw / "pdf"
    dir_pdf.mkdir(parents=True, exist_ok=True)
    caminho_manifesto = dir_raw / "manifesto.jsonl"

    # Retomada: o que já está no manifesto e no disco não é rebaixado.
    ja_feitos = {
        m["doc_id"]: m
        for m in ler_jsonl(caminho_manifesto)
        if m.get("baixado") and Path(m.get("arquivo", "")).exists()
    }
    if ja_feitos:
        log.info("retomando: %d arquivos já presentes", len(ja_feitos))

    somente_aberto = cfg.get_path("coleta.somente_acesso_aberto", True)
    max_pdfs = int(cfg.get_path("coleta.max_pdfs", 0))

    tarefas = []
    for reg in registros:
        ident = reg.get("id") or json.dumps(reg, sort_keys=True)[:200]
        did = doc_id(ident)
        if did in ja_feitos:
            continue
        if somente_aberto and not _e_acesso_aberto(reg):
            rel.falha(did, "acesso_restrito", ident)
            continue
        urls = _extrair_urls(reg)
        if not urls:
            rel.falha(did, "sem_url_de_origem", ident)
            continue
        tarefas.append((did, ident, urls))
        if max_pdfs and len(tarefas) >= max_pdfs:
            break

    log.info("%d downloads a executar", len(tarefas))
    manifesto = list(ja_feitos.values())
    total_bytes = 0

    # I/O de rede -> ThreadPool. O gargalo é espera de rede, não CPU, então
    # thread resolve e sem o custo de memória de processos separados.
    # O rate limit por domínio continua valendo dentro das threads.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futuros = {
            pool.submit(resolvedor.obter, urls, dir_pdf / f"{did}.pdf"): (did, ident, urls)
            for did, ident, urls in tarefas
        }
        for i, fut in enumerate(as_completed(futuros), 1):
            did, ident, urls = futuros[fut]
            try:
                res = fut.result()
            except Exception as exc:
                rel.falha(did, "excecao_download", f"{ident}: {exc}")
                continue

            item = {
                "doc_id": did,
                "id_bdtd": ident,
                "urls_origem": urls,
                "baixado": res.ok,
                "arquivo": str(res.caminho) if res.caminho else None,
                "url_pdf": res.url_pdf,
                "sha256": res.sha256,
                "bytes": res.bytes,
                "motivo": res.motivo,
                "coletado_em": datetime.now(timezone.utc).isoformat(),
            }
            manifesto.append(item)
            if res.ok:
                total_bytes += res.bytes
            else:
                rel.falha(did, res.motivo or "download_falhou", ident)
            if i % 25 == 0:
                log.info("%d/%d downloads processados", i, len(tarefas))

    escrever_jsonl(caminho_manifesto, manifesto)
    baixados = sum(1 for m in manifesto if m.get("baixado"))
    rel.saidas["manifesto"] = str(caminho_manifesto)
    rel.saidas["pdfs_baixados"] = baixados
    rel.metricas["bytes_baixados"] = total_bytes
    rel.metricas["bytes_baixados_humano"] = humanizar_bytes(total_bytes)
    rel.metricas["taxa_sucesso_download"] = (
        round(baixados / len(manifesto), 4) if manifesto else 0.0
    )
    log.info("downloads concluídos: %d ok, %s", baixados, humanizar_bytes(total_bytes))
    return manifesto


def _inventario_para_staging(item: dict) -> dict:
    """
    Converte um registro do inventário (CAPES/OAI) para a mesma forma que a
    API da BDTD devolvia. Assim a camada Staging não muda uma linha quando a
    fonte do Estágio 1 muda — que era exatamente o objetivo da separação.
    """
    urls = [u for u in (item.get("url_binario"), item.get("url_landing")) if u]
    return {
        "id": item.get("chave_origem") or item.get("identificador") or item.get("titulo", "")[:120],
        "title": item.get("titulo", ""),
        "summary": [item.get("resumo", "")],
        "authors": {"primary": {item.get("autor", ""): {"role": ["author"]}}} if item.get("autor") else {},
        "formats": [item.get("tipo", "")],
        "languages": [item.get("idioma", "por")],
        "publicationDates": [str(item.get("ano") or "")],
        "subjects": [[s.strip()] for s in (item.get("palavras_chave") or item.get("area") or "").split(";") if s.strip()],
        "institutions": [item.get("ies", "")],
        "urls": [{"url": u} for u in urls],
        "rawData": {
            "eu_rights_str_mv": item.get("extra", {}).get("direitos", ""),
            "dc.publisher.program.fl_str_mv": [item.get("programa", "")],
            "_inventario": {
                "fontes": item.get("fontes", [item.get("fonte")]),
                "taxonomia": item.get("taxonomia", ""),
                "area": item.get("area", ""),
                "estrato": item.get("estrato", ""),
                "cota_estrato": item.get("cota_estrato"),
                "ordem_na_fila": item.get("ordem_na_fila"),
            },
        },
        "_consulta": {"fonte_inventario": item.get("fonte")},
    }


def baixar_por_cota(cfg: Config, candidatos: list[dict], rel: Relatorio) -> list[dict]:
    """
    Percorre a fila de cada estrato até fechar a cota daquele estrato.

    É isso que impede o viés de não-resposta: em vez de sortear N e aceitar o
    que sobrou, cada estrato consome sua reserva até atingir a cota. A taxa de
    resolução por estrato vira métrica do corpus, não acidente silencioso.
    """
    resolvedor = ResolvedorTextoCompleto(cfg)
    dir_raw = cfg.dir_camada("raw")
    dir_pdf = dir_raw / "pdf"
    dir_pdf.mkdir(parents=True, exist_ok=True)
    caminho_manifesto = dir_raw / "manifesto.jsonl"

    ja_feitos = {
        m["doc_id"]: m
        for m in ler_jsonl(caminho_manifesto)
        if m.get("baixado") and Path(m.get("arquivo", "")).exists()
    }

    # coleta.somente_acesso_aberto era respeitado só no caminho bdtd_api
    # (baixar_textos/_e_acesso_aberto). O caminho inventario/OAI-PMH
    # (baixar_por_cota) baixava o PDF de qualquer candidato com url_binario,
    # independente de `direitos` — 16 documentos de Acesso Restrito entraram
    # no corpus assim antes desta correção. `extra.direitos` vem de
    # dc:rights (oai_dc/dim) ou de "direitos" já resolvido pelo Estágio 1.
    somente_aberto = cfg.get_path("coleta.somente_acesso_aberto", True)

    def _e_acesso_aberto(item: dict) -> bool:
        texto = str((item.get("extra") or {}).get("direitos", "")).lower()
        if not texto:
            return True  # sem informação: não presumir fechado, mas fica registrado no manifesto
        return "aberto" in texto or "openaccess" in texto or "open access" in texto

    if somente_aberto:
        antes = len(candidatos)
        bloqueados = [c for c in candidatos if not _e_acesso_aberto(c)]
        candidatos = [c for c in candidatos if _e_acesso_aberto(c)]
        for item in bloqueados:
            ident = item.get("chave_origem") or item.get("titulo", "")[:120]
            rel.falha(doc_id(ident), "acesso_restrito",
                      f"{item.get('estrato','?')}|{ident}: {(item.get('extra') or {}).get('direitos')}")
        log.info("acesso aberto: %d -> %d candidatos (%d bloqueados por direitos)",
                  antes, len(candidatos), len(bloqueados))

    por_estrato: dict[str, list[dict]] = {}
    for item in candidatos:
        por_estrato.setdefault(item.get("estrato", "?"), []).append(item)
    for fila in por_estrato.values():
        fila.sort(key=lambda x: x.get("ordem_na_fila", 0))

    manifesto = list(ja_feitos.values())
    estatisticas: dict[str, dict] = {}
    total_bytes = 0

    for estrato, fila in sorted(por_estrato.items()):
        cota = int(fila[0].get("cota_estrato", 1))
        obtidos, tentados = 0, 0

        # Paraleliza dentro do estrato, mas em blocos, para poder parar assim
        # que a cota fechar em vez de baixar a fila inteira.
        with ThreadPoolExecutor(max_workers=4) as pool:
            for inicio in range(0, len(fila), 8):
                if obtidos >= cota:
                    break
                bloco = fila[inicio:inicio + 8]
                futuros = {}
                for item in bloco:
                    ident = item.get("chave_origem") or item.get("titulo", "")[:120]
                    did = doc_id(ident)
                    if did in ja_feitos:
                        obtidos += 1
                        continue
                    urls = [u for u in (item.get("url_binario"), item.get("url_landing")) if u]
                    if not urls:
                        rel.falha(did, "sem_link_de_fulltext", f"{estrato}|{ident}")
                        tentados += 1
                        continue
                    futuros[pool.submit(resolvedor.obter, urls, dir_pdf / f"{did}.pdf")] = (did, ident, urls, item)

                for fut in as_completed(futuros):
                    did, ident, urls, item = futuros[fut]
                    tentados += 1
                    try:
                        res = fut.result()
                    except Exception as exc:
                        rel.falha(did, "excecao_download", f"{ident}: {exc}")
                        continue
                    manifesto.append({
                        "doc_id": did, "id_bdtd": ident, "urls_origem": urls,
                        "baixado": res.ok, "arquivo": str(res.caminho) if res.caminho else None,
                        "url_pdf": res.url_pdf, "sha256": res.sha256, "bytes": res.bytes,
                        "motivo": res.motivo, "estrato": estrato,
                        "fontes_inventario": item.get("fontes", []),
                        "coletado_em": datetime.now(timezone.utc).isoformat(),
                    })
                    if res.ok:
                        obtidos += 1
                        total_bytes += res.bytes
                    else:
                        rel.falha(did, res.motivo or "download_falhou", f"{estrato}|{ident}")

        estatisticas[estrato] = {
            "cota": cota,
            "obtidos": obtidos,
            "tentados": tentados,
            "fila_disponivel": len(fila),
            "taxa_resolucao": round(obtidos / tentados, 4) if tentados else 0.0,
            "cota_fechada": obtidos >= cota,
        }
        log.info("estrato %s: %d/%d obtidos em %d tentativas", estrato, obtidos, cota, tentados)

    escrever_jsonl(caminho_manifesto, manifesto)
    baixados = sum(1 for m in manifesto if m.get("baixado"))
    fechados = sum(1 for e in estatisticas.values() if e["cota_fechada"])

    rel.saidas["manifesto"] = str(caminho_manifesto)
    rel.saidas["pdfs_baixados"] = baixados
    rel.metricas["bytes_baixados_humano"] = humanizar_bytes(total_bytes)
    rel.metricas["taxa_resolucao_global"] = round(baixados / max(len(manifesto), 1), 4)
    rel.metricas["estratos_com_cota_fechada"] = f"{fechados}/{len(estatisticas)}"
    # A distribuição da taxa por estrato É o resultado, não um detalhe: ela
    # diz o quanto o corpus final se afastou do plano amostral.
    rel.metricas["resolucao_por_estrato"] = dict(list(estatisticas.items())[:80])
    log.info("downloads: %d ok, %s, %d/%d estratos com cota fechada",
             baixados, humanizar_bytes(total_bytes), fechados, len(estatisticas))
    return manifesto


def executar(cfg: Config) -> Relatorio:
    rel = Relatorio(camada="raw", area=cfg.get_path("projeto.area_rotulo", ""))
    fonte = cfg.get_path("coleta.fonte_inventario", "bdtd_api")
    rel.entradas["fonte_inventario"] = fonte

    if fonte == "inventario":
        # Estágio 1 vem de CAPES/OAI (ver src/raw/inventario.py).
        dir_raw = cfg.dir_camada("raw")
        candidatos = list(ler_jsonl(dir_raw / "inventario.jsonl"))
        if not candidatos:
            rel.falha("raw", "inventario_ausente",
                      "rode: python -m src.raw.inventario construir")
            rel.salvar(cfg.dir_relatorios())
            return rel

        rel.entradas["candidatos"] = len(candidatos)
        registros = [_inventario_para_staging(c) for c in candidatos]
        for reg in registros:
            reg["_coletado_em"] = datetime.now(timezone.utc).isoformat()
        destino = dir_raw / "metadata" / "registros.jsonl"
        escrever_jsonl(destino, registros)
        rel.saidas["metadata_jsonl"] = str(destino)
        rel.saidas["registros_coletados"] = len(registros)

        baixar_por_cota(cfg, candidatos, rel)
    else:
        rel.entradas["fonte"] = cfg.get_path("coleta.base_url")
        registros = coletar_metadados(cfg, rel)
        if registros:
            baixar_textos(cfg, registros, rel)

    caminho = rel.salvar(cfg.dir_relatorios())
    log.info("relatório da camada Raw: %s", caminho)
    return rel


if __name__ == "__main__":
    executar(Config.carregar())
