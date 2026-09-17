"""Classificação de movimentos da Tabela Processual Unificada (TPU/CNJ).

O DataJud devolve cada movimento como ``{"codigo": int, "nome": str, ...}``.
Os códigos variam entre nós da TPU e devem ser conferidos no SGT do CNJ
(https://www.cnj.jus.br/sgt/consulta_publica_movimentos.php) antes de se
confiar em qualquer lista fixa. Por isso a classificação padrão aqui é feita
pelo *nome* do movimento, que é estável e auditável a olho nu, e os códigos
entram apenas como sobreposição opcional via arquivo de configuração.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ACORDAO = "acordao"
MONOCRATICA = "monocratica"
OUTRO = "outro"


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços colapsados."""
    if not texto:
        return ""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


# Ordem importa: a primeira regra que casar define a classe.
_REGRAS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (MONOCRATICA, re.compile(r"\bdecisao monocratica\b|\bmonocratic")),
    (ACORDAO, re.compile(r"\bacordao\b")),
    (ACORDAO, re.compile(r"\bjulgamento\b.*\bcolegiad")),
)


@dataclass
class Classificador:
    """Classifica movimentos em acórdão / monocrática / outro.

    ``codigos_acordao`` e ``codigos_monocratica`` são conferidos antes das
    regras de nome; preencha-os a partir do SGT para tornar a classificação
    determinística.
    """

    codigos_acordao: set[int] = field(default_factory=set)
    codigos_monocratica: set[int] = field(default_factory=set)

    @classmethod
    def de_arquivo(cls, caminho: str | Path) -> "Classificador":
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        return cls(
            codigos_acordao=set(dados.get("codigos_acordao", [])),
            codigos_monocratica=set(dados.get("codigos_monocratica", [])),
        )

    def classificar(self, movimento: dict) -> str:
        codigo = movimento.get("codigo")
        if isinstance(codigo, int):
            if codigo in self.codigos_monocratica:
                return MONOCRATICA
            if codigo in self.codigos_acordao:
                return ACORDAO

        nome = normalizar(str(movimento.get("nome", "")))
        for classe, padrao in _REGRAS:
            if padrao.search(nome):
                return classe
        return OUTRO

    def movimentos_decisorios(self, movimentos: list[dict]) -> list[dict]:
        """Devolve apenas os movimentos que são acórdão ou monocrática.

        Cada item ganha a chave ``tipo_decisao``.
        """
        saida = []
        for mov in movimentos or []:
            classe = self.classificar(mov)
            if classe in (ACORDAO, MONOCRATICA):
                saida.append({**mov, "tipo_decisao": classe})
        return saida
