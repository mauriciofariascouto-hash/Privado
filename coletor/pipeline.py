"""Junta as duas fontes: DJE identifica o relator, DataJud traz os metadados."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .datajud import ClienteDataJud, apenas_digitos
from .dje import Ocorrencia, baixar_caderno, data_do_caderno, extrair_ocorrencias, extrair_texto
from .tpu import Classificador

log = logging.getLogger(__name__)

COLUNAS = [
    "numero_processo",
    "tipo_decisao",
    "data_publicacao",
    "edicao",
    "caderno",
    "classe",
    "assuntos",
    "orgao_julgador",
    "grau",
    "data_ajuizamento",
    "movimentos_decisorios",
    "trecho",
]


def varrer_dje(
    nome_relator: str,
    edicao_inicial: int,
    edicao_final: int,
    cadernos: Iterable[int] = (4,),
    cache: Path | None = None,
    data_minima: str | None = None,
) -> tuple[list[Ocorrencia], dict[int, str]]:
    """Varre um intervalo de edições do DJE atrás do relator.

    Devolve as ocorrências e o mapa ``edição -> data de publicação (ISO)``.
    Edições ausentes (feriados, numeração salteada) são puladas.
    """
    ocorrencias: list[Ocorrencia] = []
    datas: dict[int, str] = {}

    for edicao in range(edicao_inicial, edicao_final + 1):
        for caderno in cadernos:
            try:
                bruto = baixar_caderno(edicao, caderno, cache=cache)
            except FileNotFoundError:
                log.info("Edição %s caderno %s não existe; pulando", edicao, caderno)
                continue
            except RuntimeError as exc:
                log.error("Edição %s caderno %s falhou: %s", edicao, caderno, exc)
                continue

            texto = extrair_texto(bruto)
            data = data_do_caderno(texto)
            if data:
                datas[edicao] = data
                if data_minima and data < data_minima:
                    log.info("Edição %s (%s) anterior ao corte; pulando", edicao, data)
                    continue

            achados = extrair_ocorrencias(texto, nome_relator, edicao, caderno)
            if achados:
                log.info("Edição %s caderno %s: %d processo(s)", edicao, caderno, len(achados))
            ocorrencias.extend(achados)

    return ocorrencias, datas


def enriquecer(
    ocorrencias: list[Ocorrencia],
    cliente: ClienteDataJud,
    classificador: Classificador | None = None,
    datas: dict[int, str] | None = None,
) -> list[dict]:
    """Agrega metadados do DataJud a cada processo identificado no DJE."""
    classificador = classificador or Classificador()
    datas = datas or {}

    numeros = sorted({o.numero_processo for o in ocorrencias})
    por_numero: dict[str, dict] = {}
    for fonte in cliente.por_numero_processo(numeros):
        chave = apenas_digitos(str(fonte.get("numeroProcesso", "")))
        if chave:
            por_numero[chave] = fonte

    faltantes = len(numeros) - len(por_numero)
    if faltantes > 0:
        log.warning("%d de %d processos sem correspondência no DataJud", faltantes, len(numeros))

    linhas = []
    for ocorrencia in ocorrencias:
        fonte = por_numero.get(apenas_digitos(ocorrencia.numero_processo), {})
        decisorios = classificador.movimentos_decisorios(fonte.get("movimentos", []))
        linhas.append(
            {
                "numero_processo": ocorrencia.numero_processo,
                "tipo_decisao": ocorrencia.tipo_decisao,
                "data_publicacao": datas.get(ocorrencia.edicao, ""),
                "edicao": ocorrencia.edicao,
                "caderno": ocorrencia.caderno,
                "classe": (fonte.get("classe") or {}).get("nome", ""),
                "assuntos": "; ".join(
                    a.get("nome", "") for a in (fonte.get("assuntos") or []) if a.get("nome")
                ),
                "orgao_julgador": (fonte.get("orgaoJulgador") or {}).get("nomeOrgao", ""),
                "grau": fonte.get("grau", ""),
                "data_ajuizamento": fonte.get("dataAjuizamento", ""),
                "movimentos_decisorios": "; ".join(
                    f"{m.get('nome')} [{m.get('tipo_decisao')}] {m.get('dataHora', '')}"
                    for m in decisorios
                ),
                "trecho": ocorrencia.trecho,
            }
        )
    return linhas


def exportar_csv(linhas: list[dict], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=COLUNAS)
        escritor.writeheader()
        escritor.writerows(linhas)


def exportar_jsonl(registros: Iterable[dict | Ocorrencia], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8") as arquivo:
        for registro in registros:
            dados = asdict(registro) if isinstance(registro, Ocorrencia) else registro
            arquivo.write(json.dumps(dados, ensure_ascii=False) + "\n")
