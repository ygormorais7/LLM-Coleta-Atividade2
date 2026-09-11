"""
Utilidades compartilhadas por todas as camadas.

Regra do projeto: nada aqui conhece regra de negócio de camada nenhuma.
São só ferramentas (config, log, hash, rate limit, relatório).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

RAIZ = Path(__file__).resolve().parents[1]
CONFIG_PADRAO = RAIZ / "config" / "config.yaml"


# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------
class Config(dict):
    """dict com acesso por caminho pontilhado: cfg.get_path('coleta.http.timeout_s')."""

    @classmethod
    def carregar(cls, caminho: str | Path | None = None) -> "Config":
        caminho = Path(caminho or os.environ.get("BDTD_CONFIG", CONFIG_PADRAO))
        with open(caminho, "r", encoding="utf-8") as fh:
            dados = yaml.safe_load(fh) or {}
        cfg = cls(dados)
        cfg["_arquivo"] = str(caminho)
        return cfg

    def get_path(self, caminho: str, padrao: Any = None) -> Any:
        no: Any = self
        for parte in caminho.split("."):
            if not isinstance(no, dict) or parte not in no:
                return padrao
            no = no[parte]
        return no

    # Caminhos absolutos das camadas, já com a área embutida.
    def dir_camada(self, camada: str) -> Path:
        base = RAIZ / self.get_path(f"caminhos.{camada}", f"data/{camada}")
        slug = self.get_path("projeto.area_slug", "geral")
        p = base / slug
        p.mkdir(parents=True, exist_ok=True)
        return p

    def dir_relatorios(self) -> Path:
        p = RAIZ / self.get_path("caminhos.relatorios", "data/reports")
        p = p / self.get_path("projeto.area_slug", "geral")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def user_agent(self) -> str:
        contato = self.get_path("projeto.contato", "contato@exemplo.br")
        inst = self.get_path("projeto.instituicao", "UFPI")
        return (
            f"bdtd-corpus/1.0 (pesquisa academica; {inst}; +mailto:{contato}) "
            "python-requests"
        )


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def configurar_log(nome: str, arquivo: Path | None = None, nivel: int = logging.INFO):
    log = logging.getLogger(nome)
    if log.handlers:
        return log
    log.setLevel(nivel)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s", "%H:%M:%S"
    )
    con = logging.StreamHandler()
    con.setFormatter(fmt)
    log.addHandler(con)
    if arquivo:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(arquivo, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    return log


# --------------------------------------------------------------------------
# Identificadores e hashes
# --------------------------------------------------------------------------
def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8", "ignore")).hexdigest()


def sha256_arquivo(caminho: Path, bloco: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for pedaco in iter(lambda: fh.read(bloco), b""):
            h.update(pedaco)
    return h.hexdigest()


def doc_id(identificador_origem: str) -> str:
    """
    ID determinístico e estável entre execuções.

    Derivar do identificador da fonte (e não de contador/UUID aleatório)
    é o que permite reprocessar uma camada sem perder a ligação com as
    anteriores — e retomar uma coleta interrompida sem duplicar nada.
    """
    return hashlib.sha1(identificador_origem.encode("utf-8")).hexdigest()[:16]


def slugificar(texto: str, limite: int = 80) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto[:limite] or "sem-titulo"


# --------------------------------------------------------------------------
# Rate limiting (por domínio, thread-safe)
# --------------------------------------------------------------------------
class RateLimiter:
    """Espaça requisições em N por segundo, com contabilidade por chave (domínio)."""

    def __init__(self, req_por_segundo: float = 0.5):
        self.intervalo = 1.0 / max(req_por_segundo, 0.001)
        self._ultimo: dict[str, float] = {}
        self._intervalos: dict[str, float] = {}
        self._lock = threading.Lock()

    def definir_intervalo(self, chave: str, segundos: float) -> None:
        """
        Intervalo específico para um domínio, sobrepondo o padrão.

        Serve para honrar `Crawl-delay` do robots.txt. Só aceita valores
        MAIORES que o padrão: um repositório pode pedir para irmos mais
        devagar, nunca para irmos mais rápido do que decidimos.
        """
        with self._lock:
            if segundos > self.intervalo:
                self._intervalos[chave] = segundos

    def aguardar(self, chave: str = "default") -> None:
        with self._lock:
            agora = time.monotonic()
            intervalo = self._intervalos.get(chave, self.intervalo)
            proximo = self._ultimo.get(chave, 0.0) + intervalo
            espera = proximo - agora
            if espera > 0:
                time.sleep(espera)
                agora = time.monotonic()
            self._ultimo[chave] = agora


# --------------------------------------------------------------------------
# JSONL
# --------------------------------------------------------------------------
def escrever_jsonl(caminho: Path, registros: Iterable[dict], modo: str = "w") -> int:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(caminho, modo, encoding="utf-8") as fh:
        for reg in registros:
            fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
            n += 1
    return n


def ler_jsonl(caminho: Path):
    if not Path(caminho).exists():
        return
    with open(caminho, "r", encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if linha:
                yield json.loads(linha)


# --------------------------------------------------------------------------
# Relatório de camada (rastreabilidade)
# --------------------------------------------------------------------------
@dataclass
class Relatorio:
    """
    Cada camada escreve um JSON: o que entrou, o que saiu, o que falhou.

    É o que torna o pipeline auditável — sem isso não dá para responder
    "por que este documento sumiu entre Processed e Curated?".
    """

    camada: str
    area: str
    inicio: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    fim: str | None = None
    duracao_s: float | None = None
    entradas: dict = field(default_factory=dict)
    saidas: dict = field(default_factory=dict)
    metricas: dict = field(default_factory=dict)
    falhas: list = field(default_factory=list)
    parametros: dict = field(default_factory=dict)
    _t0: float = field(default_factory=time.monotonic, repr=False)

    def falha(self, identificador: str, tipo: str, detalhe: str = "") -> None:
        """Falha NUNCA é silenciada: é registrada com tipo explícito."""
        self.falhas.append({"id": identificador, "tipo": tipo, "detalhe": detalhe[:500]})

    def contar_falhas_por_tipo(self) -> dict:
        contagem: dict[str, int] = {}
        for f in self.falhas:
            contagem[f["tipo"]] = contagem.get(f["tipo"], 0) + 1
        return dict(sorted(contagem.items(), key=lambda kv: -kv[1]))

    def salvar(self, dir_relatorios: Path) -> Path:
        self.fim = datetime.now(timezone.utc).isoformat()
        self.duracao_s = round(time.monotonic() - self._t0, 2)
        self.metricas["falhas_por_tipo"] = self.contar_falhas_por_tipo()
        self.metricas["total_falhas"] = len(self.falhas)
        dir_relatorios.mkdir(parents=True, exist_ok=True)
        destino = dir_relatorios / f"{self.camada}.json"
        payload = {
            k: v for k, v in self.__dict__.items() if not k.startswith("_")
        }
        def _serializavel(obj):
            # pandas/numpy devolvem int64, float64 e Timestamp, que o json
            # não conhece. Converter aqui evita espalhar int() pelo código.
            if hasattr(obj, "item"):
                return obj.item()
            return str(obj)

        with open(destino, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=_serializavel)
        return destino


def humanizar_bytes(n: int) -> str:
    for unidade in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unidade}"
        n /= 1024.0
    return f"{n:.1f} PB"
