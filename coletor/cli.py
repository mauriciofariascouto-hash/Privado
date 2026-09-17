"""Interface de linha de comando do coletor."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .datajud import ClienteDataJud
from .dje import ANCORA_DATA, ANCORA_EDICAO, extrair_ocorrencias, extrair_texto
from .pipeline import enriquecer, exportar_csv, exportar_jsonl, varrer_dje
from .tpu import Classificador

RELATOR_PADRAO = "João Henrique Blasi"


def _configurar_log(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )


def _classificador(caminho: str | None) -> Classificador:
    return Classificador.de_arquivo(caminho) if caminho else Classificador()


def cmd_varrer(args: argparse.Namespace) -> int:
    ocorrencias, datas = varrer_dje(
        nome_relator=args.relator,
        edicao_inicial=args.edicao_inicial,
        edicao_final=args.edicao_final,
        cadernos=args.cadernos,
        cache=Path(args.cache) if args.cache else None,
        data_minima=args.data_minima,
    )
    saida = Path(args.saida)
    exportar_jsonl(ocorrencias, saida)
    Path(f"{saida}.datas.json").write_text(
        json.dumps(datas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(ocorrencias)} ocorrência(s) -> {saida}", file=sys.stderr)
    return 0


def cmd_enriquecer(args: argparse.Namespace) -> int:
    from .dje import Ocorrencia

    entrada = Path(args.entrada)
    ocorrencias = [
        Ocorrencia(**json.loads(linha))
        for linha in entrada.read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]
    datas_path = Path(f"{entrada}.datas.json")
    datas = (
        {int(k): v for k, v in json.loads(datas_path.read_text(encoding="utf-8")).items()}
        if datas_path.exists()
        else {}
    )

    linhas = enriquecer(
        ocorrencias,
        ClienteDataJud(),
        classificador=_classificador(args.codigos_tpu),
        datas=datas,
    )
    exportar_csv(linhas, Path(args.saida))
    print(f"{len(linhas)} linha(s) -> {args.saida}", file=sys.stderr)
    return 0


def cmd_local(args: argparse.Namespace) -> int:
    """Processa um caderno já salvo em disco — útil sem acesso de rede."""
    bruto = Path(args.arquivo).read_bytes()
    texto = extrair_texto(bruto)
    ocorrencias = extrair_ocorrencias(texto, args.relator, args.edicao, args.caderno)
    exportar_jsonl(ocorrencias, Path(args.saida))
    print(f"{len(ocorrencias)} ocorrência(s) -> {args.saida}", file=sys.stderr)
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coletor",
        description="Coleta acórdãos e decisões monocráticas do TJSC por relator.",
    )
    parser.add_argument("-v", "--verboso", action="store_true")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_varrer = sub.add_parser("varrer", help="varre edições do DJE atrás do relator")
    p_varrer.add_argument("--relator", default=RELATOR_PADRAO)
    p_varrer.add_argument("--edicao-inicial", type=int, default=ANCORA_EDICAO)
    p_varrer.add_argument("--edicao-final", type=int, required=True)
    p_varrer.add_argument("--cadernos", type=int, nargs="+", default=[4])
    p_varrer.add_argument("--data-minima", default=ANCORA_DATA)
    p_varrer.add_argument("--cache", default="dados/cache")
    p_varrer.add_argument("--saida", default="dados/ocorrencias.jsonl")
    p_varrer.set_defaults(func=cmd_varrer)

    p_enriq = sub.add_parser("enriquecer", help="agrega metadados do DataJud")
    p_enriq.add_argument("--entrada", default="dados/ocorrencias.jsonl")
    p_enriq.add_argument("--saida", default="dados/resultado.csv")
    p_enriq.add_argument("--codigos-tpu", help="JSON com codigos_acordao/codigos_monocratica")
    p_enriq.set_defaults(func=cmd_enriquecer)

    p_local = sub.add_parser("local", help="processa um caderno salvo em disco")
    p_local.add_argument("arquivo")
    p_local.add_argument("--relator", default=RELATOR_PADRAO)
    p_local.add_argument("--edicao", type=int, required=True)
    p_local.add_argument("--caderno", type=int, default=4)
    p_local.add_argument("--saida", default="dados/ocorrencias.jsonl")
    p_local.set_defaults(func=cmd_local)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    _configurar_log(args.verboso)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
