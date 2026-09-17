"""Leitura do Diário da Justiça Eletrônico do TJSC para identificar o relator.

Motivação: o relator não existe como campo no DataJud. O DJE, por outro lado,
publica o nome do relator junto ao número do processo, então ele serve como
fonte de *identificação*; o DataJud entra depois como fonte de metadados.

Endpoint observado (confira contra o site antes de rodar em volume):
``https://busca.tjsc.jus.br/dje-consulta/rest/diario/caderno?edicao=<n>&cdCaderno=<c>``
"""

from __future__ import annotations

import html
import logging
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .tpu import ACORDAO, MONOCRATICA, OUTRO, normalizar

log = logging.getLogger(__name__)

URL_CADERNO = "https://busca.tjsc.jus.br/dje-consulta/rest/diario/caderno"

# Âncora observada em resultado de busca: edição 4174 = 29/01/2024.
# Serve só como ponto de partida para varredura; a data real é lida do conteúdo.
ANCORA_EDICAO = 4174
ANCORA_DATA = "2024-01-29"

RE_PROCESSO = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
RE_DATA_EXTENSO = re.compile(
    r"\b(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})\b", re.IGNORECASE
)
_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


@dataclass(frozen=True)
class Ocorrencia:
    """Um processo encontrado no DJE atribuído ao relator procurado."""

    numero_processo: str
    edicao: int
    caderno: int
    tipo_decisao: str
    trecho: str


def _limpar_html(bruto: str) -> str:
    sem_script = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", bruto)
    sem_tags = re.sub(r"(?s)<[^>]+>", " ", sem_script)
    return re.sub(r"\s+", " ", html.unescape(sem_tags)).strip()


def extrair_texto(conteudo: bytes, content_type: str = "") -> str:
    """Converte o caderno bruto em texto. PDF exige ``pdftotext`` no PATH."""
    cabecalho = conteudo[:5]
    if cabecalho.startswith(b"%PDF") or "pdf" in content_type.lower():
        try:
            resultado = subprocess.run(
                ["pdftotext", "-layout", "-", "-"],
                input=conteudo,
                capture_output=True,
                check=True,
            )
            return resultado.stdout.decode("utf-8", "replace")
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                "Caderno em PDF e 'pdftotext' indisponível — instale o poppler-utils"
            ) from exc

    texto = conteudo.decode("utf-8", "replace")
    return _limpar_html(texto) if "<" in texto[:2000] else texto


def baixar_caderno(
    edicao: int,
    caderno: int = 4,
    cache: Path | None = None,
    timeout: int = 120,
    tentativas: int = 4,
) -> bytes:
    """Baixa um caderno do DJE, com cache em disco e backoff exponencial."""
    destino = cache / f"dje_{edicao}_{caderno}.bin" if cache else None
    if destino and destino.exists():
        return destino.read_bytes()

    url = f"{URL_CADERNO}?edicao={edicao}&cdCaderno={caderno}"
    ultima: Exception | None = None

    for tentativa in range(tentativas):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resposta:
                conteudo = resposta.read()
            if destino:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(conteudo)
            return conteudo
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(f"Edição {edicao} caderno {caderno} inexistente") from exc
            ultima = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            ultima = exc

        espera = 2 ** (tentativa + 1)
        log.warning("DJE edição %s falhou (%s); retry em %ss", edicao, ultima, espera)
        time.sleep(espera)

    raise RuntimeError(f"Não foi possível baixar a edição {edicao}") from ultima


def data_do_caderno(texto: str) -> str | None:
    """Extrai a data de publicação (ISO) do cabeçalho do caderno."""
    achado = RE_DATA_EXTENSO.search(texto[:4000])
    if not achado:
        return None
    dia, mes_nome, ano = achado.groups()
    mes = _MESES.get(normalizar(mes_nome))
    if not mes:
        return None
    return f"{int(ano):04d}-{mes:02d}-{int(dia):02d}"


def _tipo_do_bloco(bloco_normalizado: str) -> str:
    if "decisao monocratica" in bloco_normalizado or "monocratic" in bloco_normalizado:
        return MONOCRATICA
    if "acordao" in bloco_normalizado:
        return ACORDAO
    return OUTRO


def variantes_do_nome(nome: str) -> list[str]:
    """Gera formas de busca do nome — completo e 'primeiro + último'."""
    limpo = normalizar(nome)
    partes = limpo.split()
    variantes = {limpo}
    if len(partes) >= 2:
        variantes.add(f"{partes[0]} {partes[-1]}")
        variantes.add(partes[-1])
    return sorted(variantes, key=len, reverse=True)


# "Relator:", "Rel. Des.", "Relatora Desembargadora" — o marcador que separa
# quem julga de quem litiga. Sem ele, um homônimo que seja parte entraria na
# coleta.
_MARCADOR_RELATORIA = r"\brel(?:ator|atora)?\b\W{0,6}(?:des(?:embargador|embargadora)?a?\b\W{0,6})?"


def regex_relatoria(nome: str) -> re.Pattern[str]:
    """Casa 'marcador de relatoria + nome' sobre texto já normalizado."""
    alternativas = "|".join(re.escape(v) for v in variantes_do_nome(nome))
    return re.compile(_MARCADOR_RELATORIA + f"(?:{alternativas})")


def segmentar_publicacoes(texto: str) -> list[tuple[str, str]]:
    """Fatia o caderno em blocos, um por processo publicado.

    Cada publicação do DJE abre com o número CNJ do processo, então o número
    serve de delimitador: um bloco vai de um número até o próximo. Números
    repetidos em sequência (a mesma publicação citando o processo mais de uma
    vez) são fundidos num bloco só.
    """
    marcas = [(m.group(0), m.start()) for m in RE_PROCESSO.finditer(texto)]
    if not marcas:
        return []

    blocos: list[tuple[str, str]] = []
    indice = 0
    while indice < len(marcas):
        numero, inicio = marcas[indice]
        seguinte = indice + 1
        while seguinte < len(marcas) and marcas[seguinte][0] == numero:
            seguinte += 1
        fim = marcas[seguinte][1] if seguinte < len(marcas) else len(texto)
        blocos.append((numero, texto[inicio:fim]))
        indice = seguinte

    return blocos


def extrair_ocorrencias(
    texto: str,
    nome_relator: str,
    edicao: int,
    caderno: int = 4,
) -> list[Ocorrencia]:
    """Devolve os processos do caderno cuja relatoria é do nome procurado.

    A busca é por bloco de publicação, não por janela de caracteres: isso
    impede que uma publicação vizinha seja atribuída ao relator errado.
    """
    padrao = regex_relatoria(nome_relator)
    encontrados: dict[str, Ocorrencia] = {}

    for numero, bloco in segmentar_publicacoes(texto):
        bloco_normalizado = normalizar(bloco)
        if not padrao.search(bloco_normalizado):
            continue

        tipo = _tipo_do_bloco(bloco_normalizado)
        anterior = encontrados.get(numero)
        # Um tipo identificado prevalece sobre um bloco ambíguo.
        if anterior and anterior.tipo_decisao != OUTRO:
            continue
        encontrados[numero] = Ocorrencia(
            numero_processo=numero,
            edicao=edicao,
            caderno=caderno,
            tipo_decisao=tipo,
            trecho=re.sub(r"\s+", " ", bloco[:400]).strip(),
        )

    return sorted(encontrados.values(), key=lambda o: o.numero_processo)
