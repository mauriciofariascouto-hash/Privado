"""Uso:
    python -m datajud tribunais
    python -m datajud processo tjsp 0000000-00.0000.0.00.0000
    python -m datajud buscar trf1 --classe 1116 --ajuizado-de 2024-01-01 --tamanho 50
    python -m datajud buscar tjrj --texto 'movimentos.nome:"Julgado procedente"' --limite 500 --jsonl
    python -m datajud raw tjsp '{"size":1,"query":{"match_all":{}}}'
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .client import DatajudClient, DatajudError
from .tribunais import TRIBUNAIS


def _imprimir(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _resumo(proc: dict[str, Any]) -> str:
    classe = (proc.get("classe") or {}).get("nome", "?")
    orgao = (proc.get("orgaoJulgador") or {}).get("nome", "?")
    movs = proc.get("movimentos") or []
    ultimo = movs[-1].get("nome", "?") if movs else "-"
    return (
        f"{proc.get('numeroProcesso')}  {proc.get('tribunal')}/{proc.get('grau')}  "
        f"{classe}  |  {orgao}  |  ajuizado {str(proc.get('dataAjuizamento'))[:10]}  |  "
        f"último movimento: {ultimo}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="datajud", description="Consulta à API Pública do DATAJUD (CNJ)")
    p.add_argument("--api-key", help="Sobrescreve DATAJUD_API_KEY / chave pública do CNJ")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tribunais", help="Lista siglas aceitas")

    sp = sub.add_parser("processo", help="Busca por número CNJ")
    sp.add_argument("tribunal")
    sp.add_argument("numero")
    sp.add_argument("--resumo", action="store_true", help="Uma linha por processo em vez de JSON")

    sb = sub.add_parser("buscar", help="Busca com filtros")
    sb.add_argument("tribunal")
    sb.add_argument("--classe", type=int, help="Código da classe (TPU)")
    sb.add_argument("--orgao", type=int, help="Código do órgão julgador")
    sb.add_argument("--assunto", type=int, help="Código do assunto (TPU)")
    sb.add_argument("--grau", help="G1, G2, JE, TR, SUP ...")
    sb.add_argument("--ajuizado-de")
    sb.add_argument("--ajuizado-ate")
    sb.add_argument("--atualizado-de")
    sb.add_argument("--atualizado-ate")
    sb.add_argument("--texto", help="query_string do Elasticsearch")
    sb.add_argument("--tamanho", type=int, default=100, help="Documentos por página (máx. 10000)")
    sb.add_argument("--limite", type=int, help="Total máximo a percorrer (pagina automaticamente)")
    sb.add_argument("--jsonl", action="store_true", help="Um JSON por linha")
    sb.add_argument("--resumo", action="store_true", help="Uma linha por processo")

    sr = sub.add_parser("raw", help="Envia um corpo Elasticsearch literal")
    sr.add_argument("tribunal")
    sr.add_argument("body", help="JSON do corpo da requisição")

    args = p.parse_args(argv)

    if args.cmd == "tribunais":
        for sigla, alias in TRIBUNAIS.items():
            print(f"{sigla:8s} {alias}")
        return 0

    cli = DatajudClient(api_key=args.api_key)
    try:
        if args.cmd == "processo":
            docs = cli.buscar_por_numero(args.tribunal, args.numero)
            if not docs:
                print("Nenhum processo encontrado.", file=sys.stderr)
                return 1
            for d in docs:
                print(_resumo(d)) if args.resumo else _imprimir(d)
            return 0

        if args.cmd == "raw":
            _imprimir(cli.search(args.tribunal, json.loads(args.body)))
            return 0

        if args.cmd == "buscar":
            filtros = dict(
                classe=args.classe,
                orgao_julgador=args.orgao,
                assunto=args.assunto,
                grau=args.grau,
                ajuizado_de=args.ajuizado_de,
                ajuizado_ate=args.ajuizado_ate,
                atualizado_de=args.atualizado_de,
                atualizado_ate=args.atualizado_ate,
                texto=args.texto,
            )
            if args.limite:
                it = cli.iterar(args.tribunal, tamanho=min(args.tamanho, args.limite), limite=args.limite, **filtros)
            else:
                it = iter(cli.hits(cli.buscar(args.tribunal, tamanho=args.tamanho, **filtros)))
            n = 0
            for d in it:
                n += 1
                if args.resumo:
                    print(_resumo(d))
                elif args.jsonl:
                    print(json.dumps(d, ensure_ascii=False))
                else:
                    _imprimir(d)
            print(f"{n} processo(s).", file=sys.stderr)
            return 0
    except DatajudError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    return 0
