"""Cliente da API Pública do DataJud (CNJ) — somente biblioteca padrão.

Limite conhecido e intencional: o DataJud **não expõe relator, magistrado nem
inteiro teor**. Este cliente serve para *enriquecer* processos já identificados
por outra fonte (ver ``coletor.dje``), agregando classe, assuntos, órgão
julgador e a linha do tempo de movimentos.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator

log = logging.getLogger(__name__)

# Chave pública divulgada pelo CNJ para a API Pública (não é credencial pessoal).
CHAVE_PUBLICA = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
ENDPOINT_TJSC = "https://api-publica.datajud.cnj.jus.br/api_publica_tjsc/_search"


def apenas_digitos(numero_processo: str) -> str:
    """O DataJud indexa o número CNJ sem máscara (20 dígitos)."""
    return re.sub(r"\D", "", numero_processo or "")


class ErroDataJud(RuntimeError):
    pass


@dataclass
class ClienteDataJud:
    endpoint: str = ENDPOINT_TJSC
    chave: str = CHAVE_PUBLICA
    timeout: int = 60
    tentativas: int = 4
    pausa_entre_paginas: float = 0.34  # cortesia com o serviço público

    def _post(self, corpo: dict[str, Any]) -> dict[str, Any]:
        dados = json.dumps(corpo).encode("utf-8")
        ultima_excecao: Exception | None = None

        for tentativa in range(self.tentativas):
            requisicao = urllib.request.Request(
                self.endpoint,
                data=dados,
                method="POST",
                headers={
                    "Authorization": f"APIKey {self.chave}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(requisicao, timeout=self.timeout) as resposta:
                    return json.loads(resposta.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                corpo_erro = exc.read().decode("utf-8", "replace")[:500]
                # 429/5xx são transitórios; 4xx restantes são erro de query.
                if exc.code != 429 and exc.code < 500:
                    raise ErroDataJud(f"HTTP {exc.code}: {corpo_erro}") from exc
                ultima_excecao = ErroDataJud(f"HTTP {exc.code}: {corpo_erro}")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                ultima_excecao = exc

            espera = 2 ** (tentativa + 1)
            log.warning("DataJud falhou (%s); nova tentativa em %ss", ultima_excecao, espera)
            time.sleep(espera)

        raise ErroDataJud(f"DataJud inacessível após {self.tentativas} tentativas") from ultima_excecao

    def buscar(self, query: dict[str, Any], tamanho: int = 100) -> Iterator[dict[str, Any]]:
        """Pagina uma query Elasticsearch via ``search_after`` e devolve os ``_source``."""
        corpo: dict[str, Any] = {
            "size": tamanho,
            "query": query,
            "sort": [{"@timestamp": {"order": "asc"}}, {"_id": {"order": "asc"}}],
        }
        cursor: list[Any] | None = None

        while True:
            if cursor is not None:
                corpo["search_after"] = cursor

            resposta = self._post(corpo)
            hits = resposta.get("hits", {}).get("hits", [])
            if not hits:
                return

            for hit in hits:
                yield hit.get("_source", {})

            if len(hits) < tamanho:
                return
            cursor = hits[-1].get("sort")
            if not cursor:
                return
            time.sleep(self.pausa_entre_paginas)

    def por_numero_processo(self, numeros: list[str], tamanho: int = 100) -> Iterator[dict[str, Any]]:
        """Busca processos por número CNJ, em lotes (``terms``)."""
        limpos = [n for n in (apenas_digitos(x) for x in numeros) if n]
        for inicio in range(0, len(limpos), tamanho):
            lote = limpos[inicio : inicio + tamanho]
            yield from self.buscar({"terms": {"numeroProcesso": lote}}, tamanho=tamanho)

    def por_orgao_julgador(
        self, nome_orgao: str, grau: str = "G2", tamanho: int = 100
    ) -> Iterator[dict[str, Any]]:
        """Busca por órgão julgador (a câmara — nunca o gabinete do relator)."""
        query = {
            "bool": {
                "must": [
                    {"match": {"orgaoJulgador.nomeOrgao": nome_orgao}},
                    {"match": {"grau": grau}},
                ]
            }
        }
        yield from self.buscar(query, tamanho=tamanho)
