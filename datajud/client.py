"""Cliente para a API Pública do DATAJUD (CNJ).

A API é um Elasticsearch somente leitura. Cada tribunal tem um índice próprio:
    POST https://api-publica.datajud.cnj.jus.br/{alias}/_search
Autenticação por header ``Authorization: APIKey <chave>``. O CNJ publica uma
chave pública de uso geral; ela pode ser trocada pela variável de ambiente
``DATAJUD_API_KEY``.

Documentação: https://datajud-wiki.cnj.jus.br/api-publica/
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from typing import Any

import requests

from .tribunais import alias_do_tribunal

BASE_URL = "https://api-publica.datajud.cnj.jus.br"

# Chave pública divulgada pelo CNJ na documentação oficial da API Pública.
CHAVE_PUBLICA_CNJ = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="

TAMANHO_MAXIMO_PAGINA = 10_000


class DatajudError(RuntimeError):
    """Erro de comunicação ou resposta inválida da API."""


def normalizar_numero_processo(numero: str) -> str:
    """Remove pontuação do número CNJ: 0000000-00.0000.0.00.0000 -> 00000000000000000000."""
    digitos = re.sub(r"\D", "", numero)
    if len(digitos) != 20:
        raise ValueError(f"Número de processo deve ter 20 dígitos, recebi {len(digitos)}: {numero!r}")
    return digitos


class DatajudClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("DATAJUD_API_KEY") or CHAVE_PUBLICA_CNJ
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"APIKey {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------ base

    def search(self, tribunal: str, body: dict[str, Any]) -> dict[str, Any]:
        """Envia um corpo Elasticsearch arbitrário para o índice do tribunal."""
        url = f"{self.base_url}/{alias_do_tribunal(tribunal)}/_search"
        try:
            resp = self.session.post(url, json=body, timeout=self.timeout)
        except requests.RequestException as exc:
            raise DatajudError(f"Falha ao chamar {url}: {exc}") from exc
        if resp.status_code != 200:
            raise DatajudError(f"HTTP {resp.status_code} em {url}: {resp.text[:500]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise DatajudError(f"Resposta não é JSON: {resp.text[:500]}") from exc

    @staticmethod
    def hits(resposta: dict[str, Any]) -> list[dict[str, Any]]:
        """Extrai só os documentos (_source) de uma resposta."""
        return [h["_source"] for h in resposta.get("hits", {}).get("hits", [])]

    # --------------------------------------------------------------- consultas

    def buscar_por_numero(self, tribunal: str, numero_processo: str) -> list[dict[str, Any]]:
        body = {
            "query": {"match": {"numeroProcesso": normalizar_numero_processo(numero_processo)}},
        }
        return self.hits(self.search(tribunal, body))

    @staticmethod
    def montar_query(
        classe: int | None = None,
        orgao_julgador: int | None = None,
        assunto: int | None = None,
        grau: str | None = None,
        ajuizado_de: str | None = None,
        ajuizado_ate: str | None = None,
        atualizado_de: str | None = None,
        atualizado_ate: str | None = None,
        texto: str | None = None,
    ) -> dict[str, Any]:
        """Monta um ``bool`` query com filtros opcionais.

        Datas no formato ISO (``2024-01-31`` ou ``2024-01-31T00:00:00``).
        """
        filtros: list[dict[str, Any]] = []
        if classe is not None:
            filtros.append({"term": {"classe.codigo": classe}})
        if orgao_julgador is not None:
            filtros.append({"term": {"orgaoJulgador.codigo": orgao_julgador}})
        if assunto is not None:
            filtros.append({"term": {"assuntos.codigo": assunto}})
        if grau is not None:
            filtros.append({"term": {"grau": grau.upper()}})
        if ajuizado_de or ajuizado_ate:
            faixa: dict[str, str] = {}
            if ajuizado_de:
                faixa["gte"] = ajuizado_de
            if ajuizado_ate:
                faixa["lte"] = ajuizado_ate
            filtros.append({"range": {"dataAjuizamento": faixa}})
        if atualizado_de or atualizado_ate:
            faixa = {}
            if atualizado_de:
                faixa["gte"] = atualizado_de
            if atualizado_ate:
                faixa["lte"] = atualizado_ate
            filtros.append({"range": {"dataHoraUltimaAtualizacao": faixa}})

        must: list[dict[str, Any]] = []
        if texto:
            must.append({"query_string": {"query": texto}})

        if not filtros and not must:
            return {"match_all": {}}
        return {"bool": {"must": must, "filter": filtros}}

    def buscar(
        self,
        tribunal: str,
        query: dict[str, Any] | None = None,
        tamanho: int = 100,
        search_after: list[Any] | None = None,
        **filtros: Any,
    ) -> dict[str, Any]:
        """Uma página de resultados. Retorna a resposta bruta (inclui ``sort`` para paginação)."""
        if tamanho < 1 or tamanho > TAMANHO_MAXIMO_PAGINA:
            raise ValueError(f"tamanho deve estar entre 1 e {TAMANHO_MAXIMO_PAGINA}")
        body: dict[str, Any] = {
            "size": tamanho,
            "query": query or self.montar_query(**filtros),
            "sort": [{"@timestamp": {"order": "asc"}}],
        }
        if search_after:
            body["search_after"] = search_after
        return self.search(tribunal, body)

    def iterar(
        self,
        tribunal: str,
        query: dict[str, Any] | None = None,
        tamanho: int = 1000,
        limite: int | None = None,
        **filtros: Any,
    ) -> Iterator[dict[str, Any]]:
        """Percorre todos os resultados usando ``search_after``."""
        query = query or self.montar_query(**filtros)
        search_after: list[Any] | None = None
        emitidos = 0
        while True:
            resposta = self.buscar(tribunal, query=query, tamanho=tamanho, search_after=search_after)
            hits = resposta.get("hits", {}).get("hits", [])
            if not hits:
                return
            for hit in hits:
                yield hit["_source"]
                emitidos += 1
                if limite is not None and emitidos >= limite:
                    return
            search_after = hits[-1].get("sort")
            if not search_after or len(hits) < tamanho:
                return
