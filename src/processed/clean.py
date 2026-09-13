"""
CAMADA PROCESSED, etapa 2 — padronização, normalização, anonimização e
filtragem de qualidade.

Três blocos independentes, nessa ordem obrigatória:

  normalizar()  -> texto legível e consistente (Unicode, PDF, boilerplate)
  anonimizar()  -> PII de terceiros removida
  avaliar()     -> heurísticas decidem se o documento entra no corpus

A ordem importa: filtrar antes de normalizar reprova documentos bons por
mojibake; anonimizar antes de normalizar faz o regex de CPF errar por causa
de espaços Unicode e hifenização.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

try:
    import ftfy
except ImportError:
    ftfy = None

from ..common import sha256_texto

MARCADOR_PAGINA = "<<<PAGINA>>>"

# --------------------------------------------------------------------------
# 1. NORMALIZAÇÃO
# --------------------------------------------------------------------------
_CTRL_PRESERVAR = {"\n", "\t"}
_ESPACOS_UNICODE = dict.fromkeys(
    [0x00A0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006,
     0x2007, 0x2008, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000, 0x200B],
    " ",
)
_LIGADURAS = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "…": "..."}

# Início do conteúdo que interessa. Antes disso vem capa, ficha
# catalográfica, folha de aprovação, dedicatória e agradecimentos — que são
# ruído altamente repetitivo e cheio de nome de terceiro.
# SUMÁRIO foi deliberadamente removido desta lista: sumário é PRÉ-textual.
# Cortar a partir dele mantinha a lista de seções inteira, com as linhas de
# pontos de preenchimento — que disparavam `linhas_repetitivas` e
# `excesso_simbolos`, e ainda envenenavam a detecção de idioma, porque a
# amostra passava a ser um sumário bilíngue em vez de prosa.
_INICIO_CONTEUDO = re.compile(
    r"^\s{0,10}(RESUMO|ABSTRACT|RESUMEN|INTRODU[ÇC][ÃA]O)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Pontos de preenchimento de sumário e listas ("RESUMO......VII").
_PREENCHIMENTO = re.compile(r"[.·•_\-–—]{4,}")
# ABNT numera as seções: "6 REFERÊNCIAS", "7. REFERÊNCIAS BIBLIOGRÁFICAS".
# O regex antigo exigia a palavra sozinha na linha e por isso falhava na
# maioria das teses — deixando referências E anexos dentro do corpus.
# Numeração multinível: "6 REFERÊNCIAS", mas também "5.7 REFERÊNCIAS" — que
# é o padrão da tese em formato de artigos, onde CADA capítulo tem sua própria
# lista. Por isso o corte usa a ÚLTIMA ocorrência: cortar na primeira
# amputaria todos os capítulos seguintes.
_INICIO_REFERENCIAS = re.compile(
    r"^\s{0,10}(?:\d{1,2}(?:\.\d{1,2}){0,2}[.)]?\s+)?"
    r"(REFER[ÊE]NCIAS(\s+BIBLIOGR[ÁA]FICAS)?|BIBLIOGRAFIA|OBRAS\s+CITADAS)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Rede de segurança: quando o cabeçalho de referências não é detectável,
# corta a partir do primeiro ANEXO/APÊNDICE. Em tese de Saúde é ali que ficam
# TCLE, instrumentos preenchidos e descrição de caso — a seção de maior risco.
_INICIO_ANEXOS = re.compile(
    r"^\s{0,10}(?:\d{1,2}(?:\.\d{1,2}){0,2}[.)]?\s+)?"
    r"(AP[ÊE]NDICES?|ANEXOS?)\s*(?:[A-Z]|[IVX]+|\d+)?\s*[-–—]?.{0,60}$",
    re.IGNORECASE | re.MULTILINE,
)


def _corrigir_encoding(texto: str) -> str:
    if ftfy:
        texto = ftfy.fix_text(texto)
    for lig, sub in _LIGADURAS.items():
        texto = texto.replace(lig, sub)
    return unicodedata.normalize("NFC", texto)


def _remover_controle(texto: str) -> str:
    return "".join(
        c for c in texto
        if c in _CTRL_PRESERVAR or unicodedata.category(c)[0] != "C"
    )


def _remover_repeticao_de_pagina(texto: str, limiar: float) -> str:
    """
    Cabeçalho e rodapé de tese se repetem em quase toda página. Se uma linha
    curta aparece como primeira ou última linha em >= limiar das páginas,
    é layout, não conteúdo.
    """
    paginas = texto.split(MARCADOR_PAGINA)
    if len(paginas) < 4:
        return texto.replace(MARCADOR_PAGINA, "\n")

    bordas = Counter()
    for pagina in paginas:
        linhas = [l.strip() for l in pagina.strip().split("\n") if l.strip()]
        for linha in linhas[:2] + linhas[-2:]:
            if 3 <= len(linha) <= 120:
                bordas[linha] += 1

    minimo = max(3, int(limiar * len(paginas)))
    repetidas = {l for l, n in bordas.items() if n >= minimo}

    limpas = []
    for pagina in paginas:
        linhas = [l for l in pagina.split("\n") if l.strip() not in repetidas]
        limpas.append("\n".join(linhas))
    return "\n".join(limpas)


def _remover_numeros_de_pagina(texto: str) -> str:
    return re.sub(r"^\s{0,10}(?:[-–—]\s*)?\d{1,4}(?:\s*[-–—])?\s*$", "", texto, flags=re.MULTILINE)


def normalizar(texto: str, cfg_limpeza: dict | None = None) -> str:
    """Pipeline de normalização em 10 etapas."""
    cfg_limpeza = cfg_limpeza or {}

    # 1. encoding, mojibake, ligaduras
    texto = _corrigir_encoding(texto)
    # 2. separadores de linha Unicode que quebram tokenizador
    texto = texto.replace("\u2028", "\n").replace("\u2029", "\n\n")
    # 3. caracteres de controle invisíveis
    texto = _remover_controle(texto)
    # 4. variantes de espaço -> espaço ASCII
    texto = texto.translate(_ESPACOS_UNICODE)
    # 5. cabeçalho/rodapé repetido entre páginas (antes de perder as marcas)
    texto = _remover_repeticao_de_pagina(
        texto, float(cfg_limpeza.get("limiar_repeticao_linha", 0.6))
    )
    # 6. números de página soltos
    texto = _remover_numeros_de_pagina(texto)
    # 7. hifenização de quebra de linha ("arqui-\ntetura" -> "arquitetura")
    texto = re.sub(r"(\w)[-‐‑–]\n\s*(\w)", r"\1\2", texto)
    # 8. pontos de preenchimento de sumário e de listas
    texto = _PREENCHIMENTO.sub(" ", texto)
    # 9. entidades HTML residuais
    if "&" in texto:
        texto = html.unescape(texto)
    # 10. espaços em branco: colapsa espaços e limita linhas em branco
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    # Cortes estruturais opcionais
    if cfg_limpeza.get("cortar_pretextuais", True):
        m = _INICIO_CONTEUDO.search(texto[:60000])
        # A guarda é proporcional, não absoluta: antes era "só corte se o
        # marcador estiver além do caractere 500", o que deixava de cortar
        # sempre que os pré-textuais eram curtos — inclusive depois de a
        # remoção dos pontos de preenchimento encolher o sumário. Agora o
        # único limite é não amputar mais de 30% do documento.
        if m and m.start() < len(texto) * 0.30:
            texto = texto[m.start():]
    if cfg_limpeza.get("cortar_pos_referencias", False):
        corte = None
        for m in _INICIO_REFERENCIAS.finditer(texto):
            if m.start() > len(texto) * 0.45:
                corte = m.start()   # última ocorrência no terço final
        if corte is None:
            for m in _INICIO_ANEXOS.finditer(texto):
                if m.start() > len(texto) * 0.45:
                    corte = m.start()
                    break           # primeiro anexo, não o último
        if corte:
            texto = texto[:corte]

    return texto.strip()


# --------------------------------------------------------------------------
# 2. ANONIMIZAÇÃO
# --------------------------------------------------------------------------
def _valida_cpf(digitos: str) -> bool:
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(digitos[i]) * (tamanho + 1 - i) for i in range(tamanho))
        dv = (soma * 10) % 11 % 10
        if dv != int(digitos[tamanho]):
            return False
    return True


def _valida_cnpj(digitos: str) -> bool:
    if len(digitos) != 14 or digitos == digitos[0] * 14:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, pos in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(digitos[i]) * pesos[i] for i in range(pos))
        dv = 11 - soma % 11
        dv = 0 if dv >= 10 else dv
        if dv != int(digitos[pos]):
            return False
    return True


def _valida_pis(digitos: str) -> bool:
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False
    soma = sum(int(d) * p for d, p in zip(digitos[:10], [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    dv = 11 - soma % 11
    return (0 if dv >= 10 else dv) == int(digitos[10])


def _valida_titulo_eleitor(digitos: str) -> bool:
    """8 dígitos sequenciais + UF (01 a 28) + 2 verificadores (regra do TSE)."""
    if len(digitos) != 12 or not 1 <= int(digitos[8:10]) <= 28:
        return False
    sp_ou_mg = digitos[8:10] in ("01", "02")

    def _dv(soma: int) -> int:
        resto = soma % 11
        if resto == 10:
            return 0
        return 1 if resto == 0 and sp_ou_mg else resto

    dv1 = _dv(sum(int(digitos[i]) * (i + 2) for i in range(8)))
    dv2 = _dv(int(digitos[8]) * 7 + int(digitos[9]) * 8 + dv1 * 9)
    return digitos[10:] == f"{dv1}{dv2}"


def _valida_cns(digitos: str) -> bool:
    """Cartão Nacional de Saúde: começa com 1, 2, 7, 8 ou 9 e soma ponderada divisível por 11."""
    if len(digitos) != 15 or digitos[0] not in "12789":
        return False
    if digitos[0] in "12" and digitos[11:14] not in ("000", "001"):
        return False
    return sum(int(d) * (15 - i) for i, d in enumerate(digitos)) % 11 == 0


def _valida_telefone(digitos: str) -> bool:
    """DDD sem zero; fixo começa com 2-5, celular com 9; intervalo de anos não é telefone."""
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11) or "0" in digitos[:2]:
        return False
    local = digitos[2:]
    if len(local) == 9:
        return local[0] == "9"
    return local[0] in "2345" and not re.fullmatch(r"(?:19|20)\d{2}(?:19|20)\d{2}", local)


# Ordem importa: e-mail antes de telefone, CNPJ antes de CPF.
# Documento que tem dígito verificador só é mascarado se o dígito confere: o
# diagnóstico de 2026-09-13 mostrou que, sem isso, DOI virava PIS/cartão SUS,
# ORCID virava título de eleitor e código de setor censitário virava cartão SUS.
_PADROES = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b"), None),
    ("URL_PERFIL", re.compile(
        r"https?://(?:www\.)?(?:facebook|instagram|linkedin|twitter|x)\.com/[\w./-]+"), None),
    ("CNPJ", re.compile(r"\b\d{2}[.\s]?\d{3}[.\s]?\d{3}[/\s]?\d{4}[-\s]?\d{2}\b"), _valida_cnpj),
    ("CPF", re.compile(r"\b\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2}\b"), _valida_cpf),
    ("CARTAO_SUS", re.compile(r"\b\d{3}[\s.]?\d{4}[\s.]?\d{4}[\s.]?\d{4}\b"), _valida_cns),
    # Separador "." ou "-" obrigatório: três números de 4 dígitos separados por
    # espaço são eixo de gráfico, não título de eleitor.
    ("TITULO_ELEITOR", re.compile(r"\b\d{4}[.-]\d{4}[.-]\d{4}\b"), _valida_titulo_eleitor),
    ("PIS_PASEP", re.compile(r"\b\d{3}[.\s]?\d{5}[.\s]?\d{2}[-\s]?\d\b"), _valida_pis),
    # Separador obrigatório e sem quebra de linha: código de procedimento sem
    # pontuação ("0101020058") e intervalo de anos quebrado em linha
    # ("2008\n2009") batiam no padrão.
    # Exceção: depois de DDD entre parênteses ou de "+55 DD" — prefixo que só
    # telefone tem — a quebra de linha vale como separador. Achado real pela
    # verificação do Curated: "(31)\n3xxx-xxxx" e "+55 31\n3xxx-xxxx" escapavam.
    ("TELEFONE", re.compile(
        r"(?<!\d)(?:"
        r"(?:\+55[ \t-]?\d{2}\s|(?:\+55[ \t-]?)?\(\d{2}\)\s?)[ \t-]?9?\d{4}[\s-]\d{4}"
        r"|(?:\+55[ \t-]?)?\d{2}[ \t-][ \t-]?9?\d{4}[ \t-]\d{4}"
        r")(?!\d)"
    ), _valida_telefone),
    ("CEP", re.compile(r"\b\d{5}-\d{3}\b"), None),
    # 7 a 10 dígitos: "RG" também é parâmetro de espectro de RMN (ganho do
    # receptor, "RG 2050") — todos os 15 achados de RG no corpus eram isso.
    ("RG", re.compile(r"\bRG[\s:nº.]{0,6}[\d.\s-]{6,13}\d\b", re.IGNORECASE),
     lambda digitos: 7 <= len(digitos) <= 10),
    # Formato antigo (LLL-NNNN, hífen obrigatório) OU Mercosul (LLLNLNN, 5º
    # caractere tem que ser LETRA). O padrão antigo aceitava [A-Z0-9] na 5ª
    # posição, o que também casa com código de composto químico/material
    # (achado real: "PEG6000" — polietilenoglicol — mascarado como placa 136
    # vezes numa tese sobre formulação de estatinas, apagando o nome do
    # composto do texto).
    ("PLACA", re.compile(r"\b[A-Z]{3}-\d{4}\b|\b[A-Z]{3}\d[A-Z]\d{2}\b"), None),
]

# Chaves de config -> nome do detector
_MAPA_DETECTORES = {
    "email": "EMAIL", "url_perfil_social": "URL_PERFIL", "cnpj": "CNPJ", "cpf": "CPF",
    "cartao_sus": "CARTAO_SUS", "titulo_eleitor": "TITULO_ELEITOR", "pis_pasep": "PIS_PASEP",
    "telefone": "TELEFONE", "cep": "CEP", "rg": "RG", "placa_veiculo": "PLACA",
}

_DETECTORES_TEXTUAIS = {"EMAIL", "URL_PERFIL"}
_IDENTIFICADORES_PROTEGIDOS = re.compile(
    r"https?://\S+|\bwww\.\S+|\bdoi:\s*\S+|\b10\.\d{4,9}/\S+|\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b",
    re.IGNORECASE,
)


_JANELA_CONTEXTO = 60


@dataclass
class ResultadoAnonimizacao:
    texto: str
    ocorrencias: dict = field(default_factory=dict)
    # Cada ocorrência com o trecho em volta JÁ mascarado: dá para auditar falso
    # positivo sem reexpor o dado.
    achados: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.ocorrencias.values())


def anonimizar(texto: str, cfg_anon: dict | None = None) -> ResultadoAnonimizacao:
    """
    Remove PII de TERCEIROS do corpo do texto.

    Nota de projeto: autor e orientador NÃO são anonimizados. São dado
    bibliográfico público (a tese é publicada com o nome deles, é assim que
    se cita), vivem nos metadados e não no corpo, e removê-los destruiria a
    proveniência do corpus. O alvo aqui é o que aparece dentro do texto:
    participante de entrevista, paciente, número de documento em anexo,
    e-mail de contato, termo de consentimento digitalizado.
    """
    cfg_anon = cfg_anon or {}
    if not cfg_anon.get("habilitada", True):
        return ResultadoAnonimizacao(texto)

    ativos = {
        _MAPA_DETECTORES[k]
        for k, v in (cfg_anon.get("detectores") or {}).items()
        if v and k in _MAPA_DETECTORES
    }
    estrategia = cfg_anon.get("estrategia", "mascara")
    ocorrencias: Counter = Counter()
    # Cada detecção vira um marcador interno; só no fim o marcador é trocado
    # pela máscara. Assim o contexto de cada achado já sai com TODAS as
    # máscaras aplicadas, inclusive as de detectores que rodaram depois.
    substituicoes: list[tuple[str, str]] = []

    def _marcar(nome: str, original: str) -> str:
        ocorrencias[nome] += 1
        if estrategia == "remove":
            troca = ""
        elif estrategia == "hash":
            troca = f"[{nome}:{sha256_texto(original)[:8]}]"
        else:
            troca = f"[{nome}]"
        substituicoes.append((nome, troca))
        return f"\x01{len(substituicoes) - 1}\x01"

    def _aplicar(texto: str, nome: str, padrao: re.Pattern, validador) -> str:
        def _sub(m: re.Match) -> str:
            if validador is None:
                return _marcar(nome, m.group(0))
            # Só substitui se o dígito verificador confere: evita destruir
            # números de tabela e códigos que "parecem" documento.
            digitos = re.sub(r"\D", "", m.group(0))
            return _marcar(nome, digitos) if validador(digitos) else m.group(0)
        return padrao.sub(_sub, texto)

    ativos_ordenados = [p for p in _PADROES if p[0] in ativos]
    for nome, padrao, validador in ativos_ordenados:
        if nome in _DETECTORES_TEXTUAIS:
            texto = _aplicar(texto, nome, padrao, validador)

    # Link, DOI e ORCID saem de cena antes dos detectores numéricos: seus
    # dígitos imitam PIS, cartão SUS e título de eleitor.
    guardados: list[str] = []

    def _guardar(m: re.Match) -> str:
        guardados.append(m.group(0))
        return f"\x00{len(guardados) - 1}\x00"

    texto = _IDENTIFICADORES_PROTEGIDOS.sub(_guardar, texto)
    for nome, padrao, validador in ativos_ordenados:
        if nome not in _DETECTORES_TEXTUAIS:
            texto = _aplicar(texto, nome, padrao, validador)
    texto = re.sub(r"\x00(\d+)\x00", lambda m: guardados[int(m.group(1))], texto)

    partes, posicoes, tamanho, cursor = [], [], 0, 0
    for m in re.finditer(r"\x01(\d+)\x01", texto):
        partes.append(texto[cursor:m.start()])
        tamanho += m.start() - cursor
        nome, troca = substituicoes[int(m.group(1))]
        posicoes.append((nome, tamanho, tamanho + len(troca)))
        partes.append(troca)
        tamanho += len(troca)
        cursor = m.end()
    partes.append(texto[cursor:])
    texto = "".join(partes)
    achados = [
        {"tipo": nome,
         "contexto": texto[max(0, ini - _JANELA_CONTEXTO):fim + _JANELA_CONTEXTO].replace("\n", " ")}
        for nome, ini, fim in posicoes
    ]

    if cfg_anon.get("ner_nomes", False):
        texto, n = _anonimizar_nomes_ner(texto, cfg_anon)
        if n:
            ocorrencias["NOME"] += n

    return ResultadoAnonimizacao(texto, dict(ocorrencias), achados)


def _anonimizar_nomes_ner(texto: str, cfg_anon: dict) -> tuple[str, int]:
    """NER de pessoas. Custoso; roda só se explicitamente habilitado."""
    try:
        import spacy
    except ImportError:
        return texto, 0
    try:
        nlp = spacy.load(cfg_anon.get("ner_modelo", "pt_core_news_lg"))
    except OSError:
        return texto, 0

    partes, contador = [], 0
    for pedaco in (texto[i:i + 90000] for i in range(0, len(texto), 90000)):
        doc = nlp(pedaco)
        saida, cursor = [], 0
        for ent in doc.ents:
            if ent.label_ != "PER":
                continue
            saida.append(pedaco[cursor:ent.start_char])
            saida.append("[NOME]")
            cursor = ent.end_char
            contador += 1
        saida.append(pedaco[cursor:])
        partes.append("".join(saida))
    return "".join(partes), contador


# --------------------------------------------------------------------------
# 3. QUALIDADE
# --------------------------------------------------------------------------
_STOPWORDS_PT = {
    "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "em", "no", "na",
    "nos", "nas", "para", "por", "com", "que", "um", "uma", "se", "ao", "à",
    "como", "mais", "foi", "são", "ser", "não", "sobre", "entre", "pelo", "pela",
}
_TOKEN = re.compile(r"\w+", re.UNICODE)


def _detectar_uma(amostra: str) -> tuple[str, float]:
    try:
        from langdetect import detect_langs, DetectorFactory
        DetectorFactory.seed = 0
        melhor = detect_langs(amostra)[0]
        return melhor.lang, float(melhor.prob)
    except Exception:
        return "", 0.0


def detectar_idioma(texto: str) -> tuple[str, float]:
    """
    Voto de três janelas retiradas do miolo do documento.

    Amostrar só o começo é uma armadilha em tese brasileira: as primeiras
    páginas costumam ter resumo em português E abstract em inglês, então o
    detector devolve confiança baixa para os dois e um documento perfeitamente
    em português é reprovado. O miolo é prosa monolíngue.
    """
    n = len(texto)
    if n > 9000:
        janelas = [texto[int(n * f): int(n * f) + 3000] for f in (0.25, 0.50, 0.75)]
    else:
        janelas = [texto[:5000]]

    votos: dict[str, list[float]] = {}
    for janela in janelas:
        lang, prob = _detectar_uma(janela)
        if lang:
            votos.setdefault(lang, []).append(prob)

    if votos:
        # vence quem aparece em mais janelas; empate desempata pela confiança média
        lang = max(votos, key=lambda k: (len(votos[k]), sum(votos[k]) / len(votos[k])))
        return lang, sum(votos[lang]) / len(votos[lang])

    # Fallback grosseiro por stopwords, para o pipeline não travar sem a lib.
    palavras = [p.lower() for p in _TOKEN.findall(texto[:5000])]
    if not palavras:
        return "un", 0.0
    prop = sum(1 for p in palavras if p in _STOPWORDS_PT) / len(palavras)
    return ("pt", min(prop * 4, 0.99)) if prop > 0.08 else ("un", 0.0)


def avaliar(texto: str, cfg_q: dict | None = None) -> dict:
    """
    Heurísticas no espírito de Gopher/RefinedWeb, calibradas para tese em
    português. Retorna as métricas E a decisão, para que o relatório possa
    explicar por que cada documento caiu.
    """
    cfg_q = cfg_q or {}
    palavras = _TOKEN.findall(texto)
    n = len(palavras)
    linhas = [l for l in texto.split("\n") if l.strip()]

    prop_alfabeticas = (
        sum(1 for p in palavras if any(c.isalpha() for c in p)) / n if n else 0.0
    )
    simbolos = texto.count("#") + texto.count("…") + texto.count("...")
    prop_simbolos = simbolos / n if n else 1.0
    tam_medio = sum(len(p) for p in palavras) / n if n else 0.0
    n_stopwords = sum(1 for p in palavras[:3000] if p.lower() in _STOPWORDS_PT)
    prop_linhas_dup = (
        1 - len(set(linhas)) / len(linhas) if linhas else 1.0
    )
    # Assinatura de OCR ruim de tabela: enxame de fragmentos de 1-2 caracteres
    # ("-T,6", "Me", "a", "O") e linhas curtíssimas. Texto corrido em português
    # fica bem abaixo destes limiares; tabela mal escaneada estoura os dois.
    prop_tokens_curtos = (
        sum(1 for p in palavras if len(p) <= 2) / n if n else 1.0
    )
    palavras_por_linha = n / len(linhas) if linhas else 0.0
    idioma, confianca = detectar_idioma(texto)

    metricas = {
        "palavras": n,
        "caracteres": len(texto),
        "linhas": len(linhas),
        "prop_palavras_alfabeticas": round(prop_alfabeticas, 4),
        "prop_simbolos": round(prop_simbolos, 4),
        "tamanho_medio_palavra": round(tam_medio, 2),
        "stopwords_pt": n_stopwords,
        "prop_linhas_duplicadas": round(prop_linhas_dup, 4),
        "prop_tokens_curtos": round(prop_tokens_curtos, 4),
        "palavras_por_linha": round(palavras_por_linha, 2),
        "idioma": idioma,
        "idioma_confianca": round(confianca, 3),
    }

    faixa = cfg_q.get("faixa_tamanho_medio_palavra", [3.0, 10.0])
    reprovacoes = []
    if n < cfg_q.get("min_palavras", 300):
        reprovacoes.append("curto_demais")
    if n > cfg_q.get("max_palavras", 400000):
        reprovacoes.append("longo_demais")
    if prop_alfabeticas < cfg_q.get("min_prop_palavras_alfabeticas", 0.75):
        reprovacoes.append("pouco_texto_alfabetico")
    if prop_simbolos > cfg_q.get("max_prop_simbolos", 0.10):
        reprovacoes.append("excesso_simbolos")
    if not (faixa[0] <= tam_medio <= faixa[1]):
        reprovacoes.append("tamanho_medio_palavra_anomalo")
    if n_stopwords < cfg_q.get("min_stopwords_pt", 8):
        reprovacoes.append("sem_stopwords_pt")
    if prop_linhas_dup > cfg_q.get("max_prop_linhas_duplicadas", 0.30):
        reprovacoes.append("linhas_repetitivas")
    # 0.55 e não 0.35: português corrido roda em torno de 0.35 por causa de
    # "a", "de", "os", "em". Só lixo de OCR de tabela passa de 0.55 — medido
    # em 0.75 no documento real que motivou este filtro.
    if prop_tokens_curtos > cfg_q.get("max_prop_tokens_curtos", 0.55):
        reprovacoes.append("ocr_fragmentado")
    if palavras_por_linha < cfg_q.get("min_palavras_por_linha", 3.0):
        reprovacoes.append("linhas_curtas_demais")
    esperado = cfg_q.get("idioma_esperado", "pt")
    if idioma != esperado:
        # Idioma diferente do esperado reprova. Mas idioma CERTO com confiança
        # baixa não reprova: em tese bilíngue o detector hesita, e descartar o
        # documento por isso jogaria fora material bom.
        reprovacoes.append(f"idioma_{idioma}_{confianca:.2f}")
    elif confianca < cfg_q.get("idioma_confianca_min", 0.65):
        metricas["alerta_idioma"] = f"confianca_baixa_{confianca:.2f}"

    metricas["aprovado"] = not reprovacoes
    metricas["motivos_reprovacao"] = reprovacoes
    return metricas
