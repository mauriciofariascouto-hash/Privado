"""Mapeamento sigla do tribunal -> alias do índice na API Pública do DATAJUD.

Fonte: https://datajud-wiki.cnj.jus.br/api-publica/endpoints
"""

_SUPERIORES = ["tst", "tse", "stj", "stm"]
_TRF = [f"trf{n}" for n in range(1, 7)]
_UF = [
    "ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt",
    "pa", "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to",
]
_TJ = [f"tj{uf}" if uf != "df" else "tjdft" for uf in _UF]
_TRT = [f"trt{n}" for n in range(1, 25)]
_TRE = [f"tre-{uf}" for uf in _UF]
_TJM = ["tjmmg", "tjmrs", "tjmsp"]

TRIBUNAIS: dict[str, str] = {
    sigla: f"api_publica_{sigla}"
    for sigla in _SUPERIORES + _TRF + _TJ + _TRT + _TRE + _TJM
}


def alias_do_tribunal(tribunal: str) -> str:
    """Aceita sigla ("tjsp", "TRF1", "tre-sp") ou alias completo ("api_publica_tjsp")."""
    chave = tribunal.strip().lower()
    if chave.startswith("api_publica_"):
        return chave
    if chave not in TRIBUNAIS:
        raise KeyError(
            f"Tribunal desconhecido: {tribunal!r}. Use uma sigla como tjsp, trf1, trt2, tre-sp, stj."
        )
    return TRIBUNAIS[chave]
