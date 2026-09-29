# Prescrição em execuções e cumprimentos – 4ª Vara Cível de Joinville (DataJud)

Script: `prescricao_joinville.py`. Só usa a biblioteca padrão do Python 3.

```bash
python3 prescricao_joinville.py --listar-orgaos          # confere o nome/código da vara
python3 prescricao_joinville.py --orgao-codigo <COD>     # ou sem o parâmetro (filtra por nome "4ª Vara Cível")
python3 prescricao_joinville.py --prazo-anos 3           # títulos cambiais (padrão: 5 anos)
```

Saída em `resultado/`: **`prescricao_4vc_joinville.xlsx`** (abas Prescritos, Todos e Critérios; gerado sem dependências), `prescritos.csv`, `todos.csv`, `bruto.json`.

## Critérios (triagem, não substitui a leitura dos autos)
- **INTERCORRENTE**: última suspensão ou arquivamento provisório sem penhora, bloqueio ou outra constrição
  depois dela, e já passado 1 ano de suspensão + o prazo prescricional (art. 921, §§ 1º a 4º-A, CPC; IAC 1/STJ).
- **INTERCORRENTE (a vencer em até 1 ano)**: o mesmo caso, mas o prazo vence nos próximos 12 meses.
- **INTERCORRENTE (paralisação)**: sem movimentação há mais de 1 ano + o prazo, mesmo sem suspensão formal.
- **DIRETA**: cumprimento de sentença que começou mais de *prazo* anos depois do trânsito em julgado (Súmula 150/STF).
  Nas execuções de título extrajudicial o DataJud não informa o vencimento do título, então a
  prescrição direta precisa ser conferida nos autos.
- Execuções fiscais ficam de fora. A coluna `observacao` avisa quando um movimento já menciona prescrição ou baixa.
