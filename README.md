# Coletor de acórdãos e monocráticas do TJSC por relator

Coleta as decisões de um desembargador do TJSC a partir de janeiro de 2024.
Configurado por padrão para o **Des. João Henrique Blasi**.

## Por que não é só DataJud

A pergunta original era se dá para fazer isso pela API Pública do DataJud.
**Não dá sozinho.** O DataJud entrega metadados processuais e o relator não é
um deles. O `_source` de cada documento tem, em essência:

`numeroProcesso`, `tribunal`, `grau`, `classe`, `assuntos[]`, `orgaoJulgador`,
`sistema`, `formato`, `nivelSigilo`, `dataAjuizamento`,
`dataHoraUltimaAtualizacao` e `movimentos[]` (código TPU, nome, data/hora).

Não há campo de magistrado/relator, nem inteiro teor, nem as peças. E o
`orgaoJulgador` no 2º grau é a **câmara**, não o gabinete — então nem por via
indireta se isola um relator.

Daí a arquitetura em duas etapas:

| Etapa | Fonte | Papel |
|---|---|---|
| 1. Identificar | DJE do TJSC | publica *relator + número do processo* |
| 2. Enriquecer | DataJud | classe, assuntos, órgão julgador, movimentos |

## Uso

Sem dependências externas — só a biblioteca padrão do Python 3.11+.
(`pdftotext`, do `poppler-utils`, é necessário apenas se os cadernos do DJE
vierem em PDF.)

```bash
# 1. Varre as edições do DJE atrás do relator
python3 -m coletor.cli varrer \
    --relator "João Henrique Blasi" \
    --edicao-inicial 4174 \
    --edicao-final 4800 \
    --data-minima 2024-01-01 \
    --saida dados/ocorrencias.jsonl

# 2. Agrega os metadados do DataJud e exporta o CSV
python3 -m coletor.cli enriquecer \
    --entrada dados/ocorrencias.jsonl \
    --saida dados/resultado.csv

# Alternativa offline: processa um caderno já salvo em disco
python3 -m coletor.cli local caderno.pdf --edicao 4174
```

Testes: `python3 -m unittest discover -s tests`

## O que está verificado e o que não está

Este código foi escrito num ambiente cuja política de rede **bloqueia
`api-publica.datajud.cnj.jus.br`, `busca.tjsc.jus.br`, `*.tjsc.jus.br` e
`comunicaapi.pje.jus.br`** (403 no proxy de egresso). Consequência:

**Verificado** — toda a lógica roda contra fixtures, com 22 testes passando:
segmentação de publicações, distinção entre relator e parte homônima,
classificação acórdão × monocrática, paginação `search_after` do DataJud,
normalização do número CNJ e o cruzamento das duas fontes.

**Não verificado — confira antes de rodar em volume:**

1. **Formato do caderno do DJE.** O endpoint
   `busca.tjsc.jus.br/dje-consulta/rest/diario/caderno?edicao=<n>&cdCaderno=<c>`
   veio de resultados de busca, não de inspeção. Não sei se devolve PDF, HTML
   ou JSON. `extrair_texto()` trata os três, mas os *regex* de relatoria foram
   calibrados contra uma fixture sintética. **Baixe uma edição real e rode
   `coletor.cli local` antes de varrer centenas.**
2. **Numeração das edições.** A âncora `4174 = 29/01/2024` veio de um snippet de
   busca. O código não confia nela: lê a data do próprio caderno
   (`data_do_caderno`) e grava o mapa `edição → data`. Mas o intervalo inicial
   de `--edicao-inicial/--edicao-final` você estima a partir dela.
3. **Códigos da TPU.** A classificação padrão é por *nome* do movimento, que é
   estável. Para torná-la determinística, preencha os códigos a partir do
   [SGT do CNJ](https://www.cnj.jus.br/sgt/consulta_publica_movimentos.php) e
   passe `--codigos-tpu codigos.json`:
   ```json
   {"codigos_acordao": [], "codigos_monocratica": []}
   ```

## Ressalva específica sobre o Des. Blasi

Ele **presidiu o TJSC**, e isso corta o período pedido ao meio. Durante a
presidência não há relatoria ordinária em câmara: as decisões saem como
Presidência (suspensão de liminar/segurança, plantão) e via Órgão Especial.
Depois, ele retoma a jurisdição em câmara — as fontes o associam à **2ª Câmara
de Direito Público** e à **4ª Câmara de Direito Comercial**.

As fontes públicas que consultei **divergem sobre as datas exatas** do mandato
(um resultado aponta o biênio 2022-2024 com posse em 02/02/2022; outro indica a
saída da presidência em 01/11/2023; a gestão 2024-2026 aparece sob o Des.
Francisco José Rodrigues de Oliveira Neto). Não consegui confirmar contra o
`tjsc.jus.br` por causa do bloqueio de rede. **Confirme o período antes de
interpretar os resultados** — uma queda no volume de acórdãos no início de 2024
pode ser efeito do cargo, não do recorte.

Por isso o coletor não filtra por câmara: varre o caderno inteiro e deixa o
`orgao_julgador` no CSV para você segmentar depois.

## Saída

CSV com: `numero_processo`, `tipo_decisao` (acordao/monocratica),
`data_publicacao`, `edicao`, `caderno`, `classe`, `assuntos`, `orgao_julgador`,
`grau`, `data_ajuizamento`, `movimentos_decisorios`, `trecho`.

## Fontes

- [API Pública do DataJud — CNJ](https://www.cnj.jus.br/sistemas/datajud/api-publica/)
- [Datajud-Wiki](https://datajud-wiki.cnj.jus.br/api-publica/)
- [Jurisprudência do TJSC](https://www.tjsc.jus.br/web/jurisprudencia)
- [SGT — movimentos da TPU](https://www.cnj.jus.br/sgt/consulta_publica_movimentos.php)
