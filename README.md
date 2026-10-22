# Privado

## DATAJUD — cliente para a API Pública do CNJ

Cliente Python + CLI para consultar a [API Pública do DATAJUD](https://datajud-wiki.cnj.jus.br/api-publica/)
(base nacional de metadados processuais do CNJ). A API é um Elasticsearch somente leitura, um índice por tribunal.

### Instalação

```bash
pip install -r requirements.txt
```

### Chave de acesso

O CNJ publica uma chave pública de uso geral na documentação oficial; ela já está embutida no cliente.
Para usar outra chave, defina `DATAJUD_API_KEY` ou passe `--api-key`.

### Uso pela linha de comando

```bash
# siglas aceitas (tjsp, trf1, trt2, tre-sp, stj, tst, ...)
python -m datajud tribunais

# busca por número CNJ (com ou sem pontuação)
python -m datajud processo tjsp 0000000-00.0000.0.00.0000
python -m datajud processo tjsp 0000000-00.0000.0.00.0000 --resumo

# busca com filtros, paginação automática por search_after
python -m datajud buscar trf1 --classe 1116 --ajuizado-de 2024-01-01 --tamanho 100 --limite 500 --jsonl
python -m datajud buscar tjrj --orgao 12345 --grau G1 --resumo

# corpo Elasticsearch literal
python -m datajud raw tjsp '{"size":1,"query":{"match_all":{}}}'
```

### Uso como biblioteca

```python
from datajud import DatajudClient

cli = DatajudClient()
docs = cli.buscar_por_numero("tjsp", "0000000-00.0000.0.00.0000")

for proc in cli.iterar("trf1", classe=1116, ajuizado_de="2024-01-01", limite=1000):
    print(proc["numeroProcesso"], proc["classe"]["nome"])

bruto = cli.search("stj", {"size": 5, "query": {"match_all": {}}})
```

Campos úteis nos documentos: `numeroProcesso`, `classe.{codigo,nome}`, `assuntos[].{codigo,nome}`,
`orgaoJulgador.{codigo,nome}`, `dataAjuizamento`, `dataHoraUltimaAtualizacao`, `grau`, `movimentos[].{codigo,nome,dataHora}`.

### Rede

O cliente fala com `https://api-publica.datajud.cnj.jus.br`. Em uma sessão Claude Code na nuvem,
o host precisa estar liberado em *Network access* nas configurações do ambiente
(ver https://code.claude.com/docs/en/cloud-environments#network-access).
