"""Testes do coletor. Rodam offline, contra fixtures."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coletor.datajud import ClienteDataJud, apenas_digitos
from coletor.dje import (
    Ocorrencia,
    data_do_caderno,
    extrair_ocorrencias,
    extrair_texto,
    regex_relatoria,
    segmentar_publicacoes,
    variantes_do_nome,
)
from coletor.pipeline import enriquecer
from coletor.tpu import ACORDAO, MONOCRATICA, OUTRO, Classificador

FIXTURES = Path(__file__).parent / "fixtures"
RELATOR = "João Henrique Blasi"


class TestTPU(unittest.TestCase):
    def test_classifica_por_nome(self):
        c = Classificador()
        self.assertEqual(c.classificar({"codigo": 1, "nome": "Acórdão"}), ACORDAO)
        self.assertEqual(c.classificar({"codigo": 2, "nome": "Decisão Monocrática"}), MONOCRATICA)
        self.assertEqual(c.classificar({"codigo": 3, "nome": "Conclusão"}), OUTRO)

    def test_codigo_tem_precedencia_sobre_nome(self):
        c = Classificador(codigos_monocratica={777})
        # Nome diria "outro"; o código explícito manda.
        self.assertEqual(c.classificar({"codigo": 777, "nome": "Julgamento"}), MONOCRATICA)

    def test_monocratica_vence_acordao_em_nome_ambiguo(self):
        c = Classificador()
        nome = "Decisão monocrática que reforma o acórdão"
        self.assertEqual(c.classificar({"codigo": 9, "nome": nome}), MONOCRATICA)

    def test_movimentos_decisorios_filtra_e_rotula(self):
        c = Classificador()
        movs = [
            {"codigo": 22, "nome": "Conclusão"},
            {"codigo": 1001, "nome": "Acórdão"},
            {"codigo": 2002, "nome": "Decisão Monocrática"},
        ]
        saida = c.movimentos_decisorios(movs)
        self.assertEqual([m["tipo_decisao"] for m in saida], [ACORDAO, MONOCRATICA])


class TestDJE(unittest.TestCase):
    def setUp(self):
        bruto = (FIXTURES / "dje_caderno_sintetico.html").read_bytes()
        self.texto = extrair_texto(bruto)

    def test_extrai_texto_limpa_tags_e_entidades(self):
        self.assertNotIn("<p>", self.texto)
        self.assertNotIn("color:red", self.texto)
        self.assertIn("João Henrique Blasi", self.texto)

    def test_le_data_do_caderno(self):
        self.assertEqual(data_do_caderno(self.texto), "2024-01-29")

    def test_variantes_do_nome(self):
        variantes = variantes_do_nome(RELATOR)
        self.assertIn("joao henrique blasi", variantes)
        self.assertIn("joao blasi", variantes)
        self.assertIn("blasi", variantes)

    def test_encontra_processos_do_relator(self):
        achados = extrair_ocorrencias(self.texto, RELATOR, edicao=4174)
        numeros = {o.numero_processo for o in achados}
        self.assertIn("0301234-56.2024.8.24.0023", numeros)
        self.assertIn("5001111-22.2024.8.24.0000", numeros)

    def test_ignora_processo_de_outro_relator(self):
        achados = extrair_ocorrencias(self.texto, RELATOR, edicao=4174)
        numeros = {o.numero_processo for o in achados}
        self.assertNotIn("0309999-88.2023.8.24.0038", numeros)

    def test_nao_captura_homonimo_que_e_parte(self):
        # "Blasi" aparece como razão social, sem marcador de relatoria antes.
        achados = extrair_ocorrencias(self.texto, RELATOR, edicao=4174)
        numeros = {o.numero_processo for o in achados}
        self.assertNotIn("5002222-33.2024.8.24.0000", numeros)

    def test_classifica_tipo_da_decisao(self):
        achados = {o.numero_processo: o for o in extrair_ocorrencias(self.texto, RELATOR, 4174)}
        self.assertEqual(achados["0301234-56.2024.8.24.0023"].tipo_decisao, ACORDAO)
        self.assertEqual(achados["5001111-22.2024.8.24.0000"].tipo_decisao, MONOCRATICA)


class ClienteFake(ClienteDataJud):
    """Substitui só o transporte HTTP; a lógica de paginação continua real."""

    def __init__(self, resposta: dict):
        super().__init__()
        self.resposta = resposta
        self.chamadas: list[dict] = []
        self.pausa_entre_paginas = 0

    def _post(self, corpo):
        self.chamadas.append(corpo)
        # Segunda página vazia encerra a paginação.
        return self.resposta if len(self.chamadas) == 1 else {"hits": {"hits": []}}


class TestDataJud(unittest.TestCase):
    def setUp(self):
        self.resposta = json.loads((FIXTURES / "datajud_resposta.json").read_text(encoding="utf-8"))

    def test_numero_sem_mascara(self):
        self.assertEqual(apenas_digitos("0301234-56.2024.8.24.0023"), "03012345620248240023")

    def test_busca_devolve_sources(self):
        cliente = ClienteFake(self.resposta)
        fontes = list(cliente.buscar({"match_all": {}}, tamanho=2))
        self.assertEqual(len(fontes), 2)
        self.assertEqual(fontes[0]["numeroProcesso"], "03012345620248240023")

    def test_busca_envia_sort_e_search_after(self):
        cliente = ClienteFake(self.resposta)
        list(cliente.buscar({"match_all": {}}, tamanho=2))
        self.assertIn("sort", cliente.chamadas[0])
        self.assertEqual(cliente.chamadas[1]["search_after"], ["2024-02-02T10:00:00.000Z", "b2"])

    def test_por_numero_processo_usa_terms_sem_mascara(self):
        cliente = ClienteFake(self.resposta)
        list(cliente.por_numero_processo(["0301234-56.2024.8.24.0023"], tamanho=2))
        termos = cliente.chamadas[0]["query"]["terms"]["numeroProcesso"]
        self.assertEqual(termos, ["03012345620248240023"])


class TestPipeline(unittest.TestCase):
    def test_enriquece_cruzando_pelo_numero(self):
        resposta = json.loads((FIXTURES / "datajud_resposta.json").read_text(encoding="utf-8"))
        ocorrencias = [
            Ocorrencia("0301234-56.2024.8.24.0023", 4174, 4, ACORDAO, "trecho a"),
            Ocorrencia("5001111-22.2024.8.24.0000", 4174, 4, MONOCRATICA, "trecho b"),
        ]
        linhas = enriquecer(
            ocorrencias,
            ClienteFake(resposta),
            datas={4174: "2024-01-29"},
        )
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0]["classe"], "Apelação Cível")
        self.assertEqual(linhas[0]["orgao_julgador"], "Segunda Câmara de Direito Público")
        self.assertEqual(linhas[0]["data_publicacao"], "2024-01-29")
        self.assertIn("[acordao]", linhas[0]["movimentos_decisorios"])
        self.assertIn("[monocratica]", linhas[1]["movimentos_decisorios"])

    def test_processo_ausente_no_datajud_nao_quebra(self):
        ocorrencias = [Ocorrencia("9999999-99.2024.8.24.0000", 4174, 4, ACORDAO, "x")]
        linhas = enriquecer(ocorrencias, ClienteFake({"hits": {"hits": []}}))
        self.assertEqual(linhas[0]["classe"], "")
        self.assertEqual(linhas[0]["numero_processo"], "9999999-99.2024.8.24.0000")


class TestSegmentacao(unittest.TestCase):
    def test_um_bloco_por_processo(self):
        texto = (
            "Apelação n. 0301234-56.2024.8.24.0023 Relator: Des. Fulano ACÓRDÃO "
            "Agravo n. 5001111-22.2024.8.24.0000 Relator: Des. Beltrano DECISÃO"
        )
        blocos = segmentar_publicacoes(texto)
        self.assertEqual([n for n, _ in blocos], [
            "0301234-56.2024.8.24.0023",
            "5001111-22.2024.8.24.0000",
        ])
        self.assertIn("Fulano", blocos[0][1])
        self.assertNotIn("Beltrano", blocos[0][1])

    def test_funde_numero_repetido_na_mesma_publicacao(self):
        texto = (
            "Apelação n. 0301234-56.2024.8.24.0023, autos 0301234-56.2024.8.24.0023 "
            "Relator: Des. João Henrique Blasi ACÓRDÃO"
        )
        blocos = segmentar_publicacoes(texto)
        self.assertEqual(len(blocos), 1)
        self.assertIn("Blasi", blocos[0][1])

    def test_texto_sem_processo_devolve_vazio(self):
        self.assertEqual(segmentar_publicacoes("nenhum numero aqui"), [])


class TestRegexRelatoria(unittest.TestCase):
    def setUp(self):
        self.padrao = regex_relatoria(RELATOR)

    def test_aceita_formas_usuais(self):
        for forma in [
            "relator: des. joao henrique blasi",
            "rel. des. joao henrique blasi",
            "relatora desembargadora joao henrique blasi",
            "relator joao blasi",
            "rel. des. blasi",
        ]:
            with self.subTest(forma=forma):
                self.assertIsNotNone(self.padrao.search(forma))

    def test_recusa_nome_sem_marcador_de_relatoria(self):
        for forma in [
            "impetrante: joao henrique blasi comercio de pecas ltda",
            "advogado: joao henrique blasi",
            "joao henrique blasi",
        ]:
            with self.subTest(forma=forma):
                self.assertIsNone(self.padrao.search(forma))


if __name__ == "__main__":
    unittest.main(verbosity=2)
