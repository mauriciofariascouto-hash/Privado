"""Cliente Python para a API Pública do DATAJUD (CNJ)."""

from .client import DatajudClient, DatajudError
from .tribunais import TRIBUNAIS, alias_do_tribunal

__all__ = ["DatajudClient", "DatajudError", "TRIBUNAIS", "alias_do_tribunal"]
