#!/usr/bin/env python3
"""
Levanta, via API Pública do DataJud (CNJ), os processos de EXECUÇÃO e
CUMPRIMENTO DE SENTENÇA da 4ª Vara Cível da Comarca de Joinville (TJSC)
e aponta os que apresentam indícios de PRESCRIÇÃO (intercorrente ou direta).

Uso:
    python3 prescricao_joinville.py --listar-orgaos      # confere o nome exato da vara
    python3 prescricao_joinville.py                      # gera os relatórios
    python3 prescricao_joinville.py --prazo-anos 3       # prazo prescricional diferente

Somente biblioteca padrão (sem pip install).

ATENÇÃO: o resultado é TRIAGEM automatizada a partir de metadados do DataJud
(que não trazem vencimento do título, natureza do crédito nem o teor das
decisões). Todo caso apontado precisa de conferência nos autos (eproc/TJSC).
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ENDPOINT = "https://api-publica.datajud.cnj.jus.br/api_publica_tjsc/_search"
# Chave pública divulgada pelo CNJ (https://datajud-wiki.cnj.jus.br/api-publica/acesso).
# Se o CNJ trocar a chave, informe a nova em DATAJUD_API_KEY.
API_KEY = os.environ.get(
    "DATAJUD_API_KEY",
    "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==",
)
IBGE_JOINVILLE = 4209102

RE_VARA = re.compile(r"\b4\s*[ªºa°]?\s*Vara\s+C[íi]vel", re.I)
RE_CLASSE = re.compile(r"execu[çc][ãa]o|cumprimento", re.I)
RE_CLASSE_CUMPR = re.compile(r"cumprimento", re.I)
RE_EXEC_FISCAL = re.compile(r"fiscal", re.I)

# Movimentos (nomes da TPU/CNJ) usados na análise
RE_SUSPENSAO = re.compile(
    r"suspens|sobrest|arquivad\w* provis|arquivamento provis|\bprovis[óo]rio\b|"
    r"execu[çc][ãa]o frustrada|n[ãa]o localiza[çc][ãa]o de bens|art\.? ?921",
    re.I,
)
RE_CONSTRICAO = re.compile(
    r"penhora|bloqueio|arresto|constri[çc]|indisponibilidade|adjudica|"
    r"aliena[çc][ãa]o|arremata|levantamento|pagamento|acordo|parcelamento",
    re.I,
)
RE_DESARQUIVA = re.compile(r"desarquiv|reativa", re.I)
RE_TRANSITO = re.compile(r"tr[âa]nsito em julgado", re.I)
RE_EVOL_CLASSE = re.compile(r"evolu[çc][ãa]o da classe|altera[çc][ãa]o da classe|classe processual", re.I)
RE_PRESCRICAO_DECL = re.compile(r"prescri", re.I)
RE_BAIXA = re.compile(r"baixa definitiva|arquivad\w* definitiv|arquivamento definitiv|extin", re.I)


def post(body):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"APIKey {API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def base_query():
    return {
        "bool": {
            "filter": [{"term": {"orgaoJulgador.codigoMunicipioIBGE": IBGE_JOINVILLE}}],
            "should": [
                {"match": {"classe.nome": "Execução"}},
                {"match": {"classe.nome": "Cumprimento"}},
            ],
            "minimum_should_match": 1,
        }
    }


def listar_orgaos():
    body = {
        "size": 0,
        "query": {"term": {"orgaoJulgador.codigoMunicipioIBGE": IBGE_JOINVILLE}},
        "aggs": {"o": {"terms": {"field": "orgaoJulgador.codigo", "size": 200},
                       "aggs": {"n": {"top_hits": {"size": 1, "_source": ["orgaoJulgador"]}}}}},
    }
    res = post(body)
    for b in res["aggregations"]["o"]["buckets"]:
        oj = b["n"]["hits"]["hits"][0]["_source"]["orgaoJulgador"]
        print(f'{oj.get("codigo")}\t{b["doc_count"]}\t{oj.get("nome")}')


def baixar(orgao_codigo=None):
    q = base_query()
    if orgao_codigo:
        q["bool"]["filter"].append({"term": {"orgaoJulgador.codigo": orgao_codigo}})
    docs, after = [], None
    while True:
        body = {"size": 1000, "query": q, "sort": [{"@timestamp": {"order": "asc"}}]}
        if after:
            body["search_after"] = after
        hits = post(body)["hits"]["hits"]
        if not hits:
            break
        docs.extend(h["_source"] for h in hits)
        after = hits[-1]["sort"]
        print(f"  {len(docs)} registros...", file=sys.stderr)
    return docs


def dt(s):
    """Aceita '2023-05-10T14:22:31.000Z', '20230510142231' e '2023-05-10'."""
    if not s:
        return None
    s = str(s).strip()
    if re.fullmatch(r"\d{14}", s):
        return datetime.strptime(s, "%Y%m%d%H%M%S")
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def movimentos(p):
    out = []
    for m in p.get("movimentos") or []:
        compl = " ".join(
            str(c.get("nome") or c.get("descricao") or "") for c in (m.get("complementosTabelados") or [])
        )
        out.append((dt(m.get("dataHora")), f'{m.get("nome", "")} {compl}'.strip(), m.get("codigo")))
    return sorted([m for m in out if m[0]], key=lambda x: x[0])


def anos(d1, d2):
    return (d2 - d1).days / 365.25


def analisar(p, hoje, prazo):
    movs = movimentos(p)
    classe = (p.get("classe") or {}).get("nome", "")
    r = {
        "numero": p.get("numeroProcesso"),
        "classe": classe,
        "orgao": (p.get("orgaoJulgador") or {}).get("nome"),
        "ajuizamento": (dt(p.get("dataAjuizamento")) or "") and dt(p.get("dataAjuizamento")).date(),
        "ultimo_movimento": movs[-1][0].date() if movs else "",
        "ultimo_movimento_desc": movs[-1][1] if movs else "",
        "tipo": "",
        "marco_inicial": "",
        "anos_decorridos": "",
        "fundamento": "",
        "observacao": "",
    }
    if any(RE_PRESCRICAO_DECL.search(m[1]) for m in movs):
        r["observacao"] = "Há movimento mencionando prescrição (conferir se já declarada). "
    if movs and RE_BAIXA.search(movs[-1][1]):
        r["observacao"] += "Último movimento indica baixa/extinção. "

    # --- Prescrição intercorrente (art. 921, §§ 1º a 4º-A, CPC; IAC 1/STJ) ---
    # Marco: última suspensão/arquivamento provisório sem constrição posterior.
    # Prazo: 1 ano de suspensão + prazo prescricional da pretensão.
    susp = [m for m in movs if RE_SUSPENSAO.search(m[1])]
    if susp:
        ult = susp[-1]
        posteriores = [m for m in movs if m[0] > ult[0]]
        if not any(RE_CONSTRICAO.search(m[1]) for m in posteriores):
            limite = ult[0] + timedelta(days=365) + timedelta(days=round(365.25 * prazo))
            decorrido = anos(ult[0], hoje)
            if hoje >= limite:
                r.update(tipo="INTERCORRENTE", marco_inicial=ult[0].date(),
                         anos_decorridos=round(decorrido, 1),
                         fundamento=f"Suspensão/arquivamento provisório em {ult[0].date()} ('{ult[1]}'), "
                                    f"sem constrição posterior; 1 ano + {prazo} anos vencidos em {limite.date()}.")
                return r
            if hoje >= limite - timedelta(days=365):
                r.update(tipo="INTERCORRENTE (a vencer em até 1 ano)", marco_inicial=ult[0].date(),
                         anos_decorridos=round(decorrido, 1),
                         fundamento=f"Vence em {limite.date()}.")
                return r

    # Paralisação prolongada sem suspensão formal (indício, exige conferência)
    if movs:
        util = [m for m in movs if not RE_BAIXA.search(m[1])]
        ref = util[-1][0] if util else movs[-1][0]
        if anos(ref, hoje) >= prazo + 1 and not RE_BAIXA.search(movs[-1][1]):
            r.update(tipo="INTERCORRENTE (paralisação)", marco_inicial=ref.date(),
                     anos_decorridos=round(anos(ref, hoje), 1),
                     fundamento=f"Sem movimentação desde {ref.date()} (> 1 + {prazo} anos).")
            return r

    # --- Prescrição direta da pretensão executiva (Súmula 150/STF) ---
    # Cumprimento de sentença: trânsito em julgado -> início do cumprimento.
    if RE_CLASSE_CUMPR.search(classe):
        tj = [m for m in movs if RE_TRANSITO.search(m[1])]
        ini = [m for m in movs if RE_EVOL_CLASSE.search(m[1]) and (not tj or m[0] > tj[0][0])]
        if tj:
            inicio = ini[0][0] if ini else None
            if inicio and anos(tj[0][0], inicio) > prazo:
                r.update(tipo="DIRETA", marco_inicial=tj[0][0].date(),
                         anos_decorridos=round(anos(tj[0][0], inicio), 1),
                         fundamento=f"Trânsito em julgado em {tj[0][0].date()} e início do cumprimento "
                                    f"em {inicio.date()} (> {prazo} anos).")
                return r
    return r


# ---------------------------------------------------------------------------
# Gravação de .xlsx sem dependências (zipfile + SpreadsheetML)
# ---------------------------------------------------------------------------
import zipfile
from xml.sax.saxutils import escape

CABECALHOS = {
    "numero": "Nº do processo", "classe": "Classe", "orgao": "Órgão julgador",
    "ajuizamento": "Ajuizamento", "ultimo_movimento": "Último movimento",
    "ultimo_movimento_desc": "Descrição do último movimento", "tipo": "Prescrição (indício)",
    "marco_inicial": "Marco inicial", "anos_decorridos": "Anos decorridos",
    "fundamento": "Fundamento", "observacao": "Observação",
}
LARGURAS = {"numero": 27, "classe": 32, "orgao": 36, "ajuizamento": 12, "ultimo_movimento": 12,
            "ultimo_movimento_desc": 40, "tipo": 30, "marco_inicial": 12, "anos_decorridos": 10,
            "fundamento": 70, "observacao": 45}


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cel(ref, v, estilo=0):
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}" s="{estilo}"><v>{v}</v></c>'
    if hasattr(v, "toordinal"):  # date -> serial do Excel
        return f'<c r="{ref}" s="2"><v>{v.toordinal() - 693594}</v></c>'
    return f'<c r="{ref}" s="{estilo}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def _planilha(campos, linhas, larguras=None):
    cols = "".join(f'<col min="{i+1}" max="{i+1}" width="{(larguras or {}).get(c, 18)}" customWidth="1"/>'
                   for i, c in enumerate(campos))
    rows = ['<row r="1">' + "".join(_cel(f"{_col(i)}1", CABECALHOS.get(c, c), 1) for i, c in enumerate(campos)) + "</row>"]
    for n, l in enumerate(linhas, start=2):
        rows.append(f'<row r="{n}">' + "".join(_cel(f"{_col(i)}{n}", l.get(c)) for i, c in enumerate(campos)) + "</row>")
    ult = f"{_col(len(campos)-1)}{max(len(linhas)+1, 1)}"
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<cols>{cols}</cols><sheetData>{"".join(rows)}</sheetData>'
            f'<autoFilter ref="A1:{ult}"/></worksheet>')


def gravar_xlsx(caminho, abas):
    """abas: lista de (nome, campos, linhas, larguras)."""
    estilos = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd/mm/yyyy"/></numFmts>'
               '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
               '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
               '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
               '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/></patternFill></fill></fills>'
               '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
               '<cellXfs count="3"><xf applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
               '<xf fontId="1" fillId="2" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'
               '<xf numFmtId="164" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top"/></xf></cellXfs>'
               '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(abas)))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(a[0])}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i, a in enumerate(abas))
                   + "</sheets><definedNames>"
                   + "".join(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">\'{a[0]}\'!$A$1:${_col(len(a[1])-1)}${max(len(a[2])+1,1)}</definedName>' for i, a in enumerate(abas))
                   + "</definedNames></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>' for i in range(len(abas)))
                   + f'<Relationship Id="rId{len(abas)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml", estilos)
        for i, (nome, campos, linhas, larg) in enumerate(abas):
            z.writestr(f"xl/worksheets/sheet{i+1}.xml", _planilha(campos, linhas, larg))


CRITERIOS = [
    ("INTERCORRENTE", "Última suspensão/arquivamento provisório sem constrição posterior; decorridos 1 ano + prazo prescricional (art. 921, §§ 1º a 4º-A, CPC; IAC 1/STJ)."),
    ("INTERCORRENTE (a vencer em até 1 ano)", "Mesma hipótese, com vencimento nos próximos 12 meses."),
    ("INTERCORRENTE (paralisação)", "Sem movimentação há mais de 1 ano + prazo prescricional, mesmo sem suspensão formal."),
    ("DIRETA", "Cumprimento de sentença iniciado mais de <prazo> anos após o trânsito em julgado (Súmula 150/STF)."),
    ("Aviso", "Triagem automatizada a partir de metadados do DataJud. Conferir cada caso nos autos (eproc/TJSC). "
              "Execução de título extrajudicial: o DataJud não informa o vencimento do título; prescrição direta deve ser verificada manualmente."),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar-orgaos", action="store_true", help="lista órgãos julgadores de Joinville")
    ap.add_argument("--orgao-codigo", type=int, help="código DataJud da vara (use após --listar-orgaos)")
    ap.add_argument("--prazo-anos", type=float, default=5,
                    help="prazo prescricional da pretensão (padrão 5: art. 206 §5º I CC; 3 p/ títulos cambiais)")
    ap.add_argument("--saida", default="resultado")
    a = ap.parse_args()

    if a.listar_orgaos:
        listar_orgaos()
        return

    docs = baixar(a.orgao_codigo)
    if not a.orgao_codigo:
        docs = [d for d in docs if RE_VARA.search((d.get("orgaoJulgador") or {}).get("nome", ""))]
    docs = [d for d in docs
            if RE_CLASSE.search((d.get("classe") or {}).get("nome", ""))
            and not RE_EXEC_FISCAL.search((d.get("classe") or {}).get("nome", ""))]
    # DataJud pode ter o mesmo processo em mais de um registro (grau/sistema): mantém o mais recente
    uniq = {}
    for d in docs:
        k = d.get("numeroProcesso")
        if k not in uniq or str(d.get("dataHoraUltimaAtualizacao", "")) > str(uniq[k].get("dataHoraUltimaAtualizacao", "")):
            uniq[k] = d
    docs = list(uniq.values())

    os.makedirs(a.saida, exist_ok=True)
    with open(os.path.join(a.saida, "bruto.json"), "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False)

    hoje = datetime.now(timezone.utc).replace(tzinfo=None)
    linhas = [analisar(d, hoje, a.prazo_anos) for d in docs]
    campos = list(linhas[0].keys()) if linhas else ["numero"]
    with open(os.path.join(a.saida, "todos.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, campos, delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    presc = sorted([l for l in linhas if l["tipo"]], key=lambda l: (l["tipo"], str(l["marco_inicial"])))
    with open(os.path.join(a.saida, "prescritos.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, campos, delimiter=";")
        w.writeheader()
        w.writerows(presc)

    crit = [{"tipo": t, "fundamento": d.replace("<prazo>", f"{a.prazo_anos:g}")} for t, d in CRITERIOS]
    crit.append({"tipo": "Prazo prescricional usado", "fundamento": f"{a.prazo_anos:g} anos"})
    crit.append({"tipo": "Data da extração", "fundamento": hoje.strftime("%d/%m/%Y %H:%M UTC")})
    xlsx = os.path.join(a.saida, "prescricao_4vc_joinville.xlsx")
    gravar_xlsx(xlsx, [
        ("Prescritos", campos, presc, LARGURAS),
        ("Todos", campos, linhas, LARGURAS),
        ("Critérios", ["tipo", "fundamento"], crit, {"tipo": 38, "fundamento": 110}),
    ])

    orgaos = sorted({l["orgao"] for l in linhas})
    print(f"Órgão(s) considerado(s): {orgaos}")
    print(f"Processos de execução/cumprimento: {len(linhas)}")
    for t in sorted({l["tipo"] for l in presc}):
        print(f"  {t}: {sum(1 for l in presc if l['tipo'] == t)}")
    print(f"Arquivos em {a.saida}/ (prescricao_4vc_joinville.xlsx, prescritos.csv, todos.csv, bruto.json)")


if __name__ == "__main__":
    main()
