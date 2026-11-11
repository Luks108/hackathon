"""Testes do pacote de prova exportável contra PHP e MariaDB de verdade (mesmo ambiente do test_api.py).

    docker compose -f site/dev/docker-compose.yml up -d
    php site/setup.php
    python site/dev/test_prova.py

O worker é simulado: os testes mandam à API os mesmos eventos que o worker manda, e depois baixam o pacote como o navegador.
O pacote é aberto fora do projeto (pasta temporária) e reconferido por cálculo próprio, sem usar código do sistema.
"""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_api import (Base, Cliente, PHP, RAIZ, WORKER_KEY, chamar, plano_unico, setUpModule, sql, tearDownModule, worker)  # noqa: E402,F401

HASH_BRUTO = hashlib.sha256(b"arquivo bruto de mentira").hexdigest()
TRECHO = "Contrato 12/2024 | Empresa Alfa Ltda | R$ 120.000,00 | vigência 01/01/2024 a 31/12/2024"


def verificar(pasta, *args):
    """Roda o verificar_prova.py que veio dentro do pacote, num Python isolado (-I) e com saída em UTF-8."""
    return subprocess.run([sys.executable, "-I", "-X", "utf8", str(pasta / "verificar_prova.py"), *args], capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def fonte(**campos):
    base = {"evidencia": "abc123:contratos:7", "trecho": TRECHO, "url": "https://portal.exemplo/contratos", "capturado_em": "2026-11-05",
            "hash_confere": True, "documento_hash": HASH_BRUTO, "arquivo": "contratos-2024.html", "tabela": "contratos", "linha": 7,
            "trecho_mascarado": False}
    base.update(campos)
    return {"tipo": "fonte", "dados": base}


def fim(**extras):
    return {"tipo": "fim", "dados": {"duracao_ms": 1200, **extras}}


MODELO = {"modelo_pedido": "deepseek:deepseek-flash", "modelo": "claude-sonnet-5-5", "tentados": ["deepseek:deepseek-flash", "claude-sonnet-5-5"],
          "trocas": [{"de": "deepseek:deepseek-flash", "para": "claude-sonnet-5-5", "motivo": "conexão recusada pelo provedor", "tentativa": 2}]}


class Prova(Base):
    def criar_em_processamento(self, c, texto, status="processando"):
        """Cria a pergunta direto no banco, já fora da fila. Um worker de verdade rodando na máquina (consultando este mesmo
        banco) só pega perguntas em "fila", então não rouba a pergunta de teste nem a responde com um modelo real."""
        uid = sql(f"SELECT id FROM usuarios WHERE email = '{c.email}'")
        pl = plano_unico()
        texto = texto.replace("'", "''")
        return int(sql(f"INSERT INTO perguntas (usuario_id, plano_id, texto, tenants, status, iniciada_em) VALUES ({uid}, {pl}, '{texto}', "
                       f"'[\"pe-estado\",\"pe-garanhuns\"]', '{status}', NOW(3)); SELECT LAST_INSERT_ID()"))

    def responder(self, c, eventos, texto="Qual o maior contrato?"):
        """Faz o papel do worker: manda à API os eventos da pergunta e devolve o id."""
        pid = self.criar_em_processamento(c, texto)
        lote = [{"seq": i + 1, **e} for i, e in enumerate(eventos)]
        w = worker(self.base, "POST", f"/api/worker/perguntas/{pid}/eventos", {"eventos": lote})
        self.assertEqual(w.status, 200, w.corpo)
        return pid

    def completa(self, c, **extras):
        return self.responder(c, [{"tipo": "consulta", "dados": {"nome": "listar_contratos"}}, fonte(),
                                  {"tipo": "texto", "dados": {"delta": "O maior contrato é de R$ 120.000,00 "}},
                                  {"tipo": "texto", "dados": {"delta": "com a Empresa Alfa."}}, fim(**extras)])

    def baixar(self, c, caminho):
        """GET com a sessão do navegador. Devolve (status, cabeçalhos, bytes)."""
        try:
            r = c.opener.open(self.base + caminho, timeout=15)
        except urllib.error.HTTPError as e:
            r = e
        return r.status if hasattr(r, "status") else r.code, r.headers, r.read()

    def json_de(self, c, caminho):
        status, _, corpo = self.baixar(c, caminho)
        self.assertEqual(status, 200, corpo[:200])
        return json.loads(corpo)

    def abrir_zip(self, dados: bytes) -> tuple[zipfile.ZipFile, Path]:
        z = zipfile.ZipFile(io.BytesIO(dados))
        self.assertIsNone(z.testzip())
        pasta = Path(tempfile.mkdtemp(prefix="prova-"))
        z.extractall(pasta)
        return z, pasta


class TestConsultaValida(Prova):
    def test_campos_obrigatorios_presentes_e_preenchidos(self):
        c = self.cliente_com_plano()
        pid = self.completa(c, **MODELO)
        doc = self.json_de(c, f"/api/perguntas/{pid}/prova?formato=json")
        self.assertEqual((doc["formato"], doc["versao_formato"], doc["algoritmo_hash"], doc["escopo"]), ("fornexia-prova", 1, "sha256", "consulta"))
        self.assertRegex(doc["exportado_em"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(len(doc["registros"]), 1)
        r = doc["registros"][0]
        self.assertEqual(r["pergunta"], "Qual o maior contrato?")
        self.assertEqual(r["resposta"], "O maior contrato é de R$ 120.000,00 com a Empresa Alfa.")   # texto integral, na ordem
        self.assertEqual(r["prova"], "com_prova")
        self.assertIsNone(r["motivo_prova"])
        self.assertEqual((r["modelo"]["pedido"], r["modelo"]["respondeu"]), ("deepseek:deepseek-flash", "claude-sonnet-5-5"))
        self.assertEqual(r["perfil"]["entes"], ["pe-estado", "pe-garanhuns"])
        self.assertIsNone(r["perfil"]["dados_pessoais"])              # não há detector confiável: não se afirma nem que tem nem que não tem
        self.assertIn("Não avaliado", r["perfil"]["dados_pessoais_nota"])
        self.assertIsNone(r["versao_extrator"])                       # não existe na coleta: ausente, com explicação
        self.assertIn("não é registrada", r["versao_extrator_nota"])
        t = r["trechos"][0]
        for campo in ("trecho", "trecho_sha256", "url", "capturado_em", "arquivo_bruto", "tabela", "linha", "documento_hash"):
            self.assertTrue(t[campo] not in (None, ""), campo)
        self.assertEqual((t["documento_hash"], t["documento_hash_algoritmo"], t["hash_conferido_na_consulta"]), (HASH_BRUTO, "sha256", True))

    def test_hash_do_trecho_recalculado_bate_com_o_declarado(self):
        c = self.cliente_com_plano()
        pid = self.completa(c)
        t = self.json_de(c, f"/api/perguntas/{pid}/prova?formato=json")["registros"][0]["trechos"][0]
        self.assertEqual(hashlib.sha256(t["trecho"].encode("utf-8")).hexdigest(), t["trecho_sha256"])

    def test_zip_abre_fora_do_projeto_e_o_hash_do_arquivo_do_trecho_bate(self):
        c = self.cliente_com_plano()
        pid = self.completa(c)
        status, cab, dados = self.baixar(c, f"/api/perguntas/{pid}/prova")
        self.assertEqual(status, 200)
        self.assertEqual(cab["Content-Type"], "application/zip")
        self.assertIn(f'filename="prova-fornexia-consulta-{pid}.zip"', cab["Content-Disposition"])
        z, pasta = self.abrir_zip(dados)
        self.assertEqual(sorted(z.namelist()), sorted(["prova.json", "LEIA-ME.txt", "verificar_prova.py", f"trechos/{pid}-1.txt"]))
        doc = json.loads((pasta / "prova.json").read_text(encoding="utf-8"))
        t = doc["registros"][0]["trechos"][0]
        bytes_do_trecho = (pasta / t["trecho_arquivo"]).read_bytes()
        self.assertEqual(hashlib.sha256(bytes_do_trecho).hexdigest(), t["trecho_sha256"])       # cálculo independente
        self.assertEqual(bytes_do_trecho.decode("utf-8"), TRECHO)                                # texto exato, sem quebra de linha
        self.assertIn("Get-FileHash", (pasta / "LEIA-ME.txt").read_text(encoding="utf-8"))

    def test_verificador_do_pacote_roda_e_detecta_adulteracao(self):
        c = self.cliente_com_plano()
        pid = self.completa(c)
        _, pasta = self.abrir_zip(self.baixar(c, f"/api/perguntas/{pid}/prova")[2])
        ok = verificar(pasta)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("CONFERE", ok.stdout)
        # arquivo bruto: pasta com o conteúdo certo confere, com o conteúdo errado não
        bruto = Path(tempfile.mkdtemp(prefix="bruto-"))
        (bruto / "contratos-2024.html").write_bytes(b"arquivo bruto de mentira")
        com_bruto = verificar(pasta, "--bruto", str(bruto))
        self.assertEqual(com_bruto.returncode, 0, com_bruto.stdout)
        (bruto / "contratos-2024.html").write_bytes(b"outro conteudo")
        errado = verificar(pasta, "--bruto", str(bruto))
        self.assertEqual(errado.returncode, 1)
        self.assertIn("NÃO CONFERE", errado.stdout)
        # trecho alterado depois da exportação
        (pasta / f"trechos/{pid}-1.txt").write_text(TRECHO.replace("120.000", "999.000"), encoding="utf-8")
        adulterado = verificar(pasta)
        self.assertEqual(adulterado.returncode, 1)
        self.assertIn("NÃO CONFERE", adulterado.stdout)


class TestSemProva(Prova):
    def test_resposta_sem_trecho_sai_marcada_sem_prova_e_sem_dado_emprestado(self):
        c = self.cliente_com_plano()
        com = self.completa(c)                                        # uma consulta com trecho, para provar que nada vaza para a outra
        sem = self.responder(c, [{"tipo": "texto", "dados": {"delta": "Não localizei esse fornecedor."}}, fim()], "Existe a empresa Zeta?")
        r = self.json_de(c, f"/api/perguntas/{sem}/prova?formato=json")["registros"][0]
        self.assertEqual(r["prova"], "sem_prova")
        self.assertIn("não citou nenhum trecho", r["motivo_prova"])
        self.assertEqual(r["trechos"], [])
        self.assertEqual(r["resposta"], "Não localizei esse fornecedor.")
        self.assertNotIn(TRECHO, json.dumps(r, ensure_ascii=False))
        _, _, zipado = self.baixar(c, f"/api/perguntas/{sem}/prova")
        self.assertFalse([n for n in zipfile.ZipFile(io.BytesIO(zipado)).namelist() if n.startswith("trechos/")])
        self.assertNotEqual(com, sem)

    def test_trecho_sem_a_cadeia_completa_nao_vira_com_prova(self):
        c = self.cliente_com_plano()
        pid = self.responder(c, [fonte(documento_hash=None, arquivo=None, tabela=None, linha=None),
                                 {"tipo": "texto", "dados": {"delta": "Resposta."}}, fim()])
        r = self.json_de(c, f"/api/perguntas/{pid}/prova?formato=json")["registros"][0]
        self.assertEqual(r["prova"], "prova_incompleta")
        self.assertIn("documento_hash", r["motivo_prova"])
        self.assertIsNone(r["trechos"][0]["documento_hash"])         # ausente continua ausente

    def test_hash_que_nao_bateu_na_consulta_nao_e_apresentado_como_prova(self):
        c = self.cliente_com_plano()
        pid = self.responder(c, [fonte(hash_confere=False), {"tipo": "texto", "dados": {"delta": "Resposta."}}, fim()])
        r = self.json_de(c, f"/api/perguntas/{pid}/prova?formato=json")["registros"][0]
        self.assertEqual(r["prova"], "prova_incompleta")
        self.assertFalse(r["trechos"][0]["hash_conferido_na_consulta"])

    def test_consulta_que_terminou_em_erro_sai_sem_prova_e_sem_resposta(self):
        c = self.cliente_com_plano()
        pid = self.responder(c, [{"tipo": "erro", "dados": {"motivo": "Não consegui concluir agora."}}])
        r = self.json_de(c, f"/api/perguntas/{pid}/prova?formato=json")["registros"][0]
        self.assertEqual((r["prova"], r["resposta"], r["status"]), ("sem_prova", None, "erro"))


class TestFallbackNoPacote(Prova):
    def test_troca_de_provedor_fica_registrada(self):
        c = self.cliente_com_plano()
        r = self.json_de(c, f"/api/perguntas/{self.completa(c, **MODELO)}/prova?formato=json")["registros"][0]
        self.assertTrue(r["fallback"]["houve_troca"])
        self.assertEqual(r["fallback"]["trocas"], MODELO["trocas"])
        self.assertEqual(r["fallback"]["modelos_tentados"], MODELO["tentados"])

    def test_sem_troca_diz_que_nao_houve(self):
        c = self.cliente_com_plano()
        extras = {"modelo_pedido": "claude-opus-5-5", "modelo": "claude-opus-5-5", "tentados": ["claude-opus-5-5"], "trocas": []}
        r = self.json_de(c, f"/api/perguntas/{self.completa(c, **extras)}/prova?formato=json")["registros"][0]
        self.assertIs(r["fallback"]["houve_troca"], False)
        self.assertEqual(r["fallback"]["trocas"], [])

    def test_worker_que_nao_informou_deixa_ausente_e_nao_inventa_tentativa(self):
        c = self.cliente_com_plano()
        r = self.json_de(c, f"/api/perguntas/{self.completa(c)}/prova?formato=json")["registros"][0]
        self.assertIsNone(r["modelo"]["respondeu"])
        self.assertIsNone(r["fallback"]["houve_troca"])
        self.assertEqual(r["fallback"]["trocas"], [])
        self.assertIn("não informou", r["modelo"]["motivo_ausente"])


class TestRecusas(Prova):
    def test_consulta_inexistente_da_erro_claro_e_nao_gera_arquivo(self):
        c = self.cliente_com_plano()
        status, cab, corpo = self.baixar(c, "/api/perguntas/99999999/prova")
        self.assertEqual(status, 404)
        self.assertTrue(cab["Content-Type"].startswith("application/json"))
        self.assertNotIn("Content-Disposition", cab)
        self.assertEqual(json.loads(corpo), {"erro": "A consulta 99999999 não existe."})

    def test_consulta_de_outra_conta_parece_inexistente(self):
        dono, outro = self.cliente_com_plano(), self.cliente_com_plano()
        pid = self.completa(dono)
        status, _, corpo = self.baixar(outro, f"/api/perguntas/{pid}/prova")
        self.assertEqual(status, 404)
        self.assertNotIn("Content-Disposition", self.baixar(outro, f"/api/perguntas/{pid}/prova")[1])
        self.assertEqual(self.baixar(outro, "/api/provas")[0], 404)       # a conta do outro não tem consulta nenhuma

    def test_exige_login(self):
        self.assertEqual(chamar(self.base, "GET", "/api/perguntas/1/prova").status, 401)
        self.assertEqual(chamar(self.base, "GET", "/api/provas").status, 401)

    def test_consulta_em_andamento_nao_exporta(self):
        c = self.cliente_com_plano()
        pid = self.criar_em_processamento(c, "Ainda respondendo?")
        status, _, corpo = self.baixar(c, f"/api/perguntas/{pid}/prova")
        self.assertEqual(status, 409)
        self.assertIn("andamento", json.loads(corpo)["erro"])

    def test_ids_invalidos(self):
        c = self.cliente_com_plano()
        for ruim in ("abc", "1,,2", "0", "1;DROP TABLE perguntas", "-3", ""):
            self.assertEqual(self.baixar(c, "/api/provas?ids=" + urllib.parse.quote(ruim))[0], 400, ruim)

    def test_metodo_post_nao_existe_na_rota(self):
        c = self.cliente_com_plano()
        self.assertEqual(c.req("POST", "/api/perguntas/1/prova").status, 405)


class TestDossie(Prova):
    def tres(self, c):
        ids = []
        for i in range(3):
            ids.append(self.responder(c, [fonte(evidencia=f"x{i}:contratos:{i}", linha=i, trecho=f"{TRECHO} #{i}"),
                                          {"tipo": "texto", "dados": {"delta": f"Resposta {i}."}}, fim()], f"Pergunta {i}?"))
        return ids

    def test_tres_consultas_saem_tres_registros_na_ordem_sem_duplicar(self):
        c = self.cliente_com_plano()
        ids = self.tres(c)
        doc = self.json_de(c, "/api/provas?formato=json")
        self.assertEqual(doc["escopo"], "dossie")
        self.assertEqual([r["pergunta_id"] for r in doc["registros"]], ids)
        self.assertEqual([r["pergunta"] for r in doc["registros"]], ["Pergunta 0?", "Pergunta 1?", "Pergunta 2?"])
        self.assertEqual([r["resposta"] for r in doc["registros"]], ["Resposta 0.", "Resposta 1.", "Resposta 2."])
        # a ordem PEDIDA vale (não a numérica), e id repetido não duplica a saída
        pedido = self.json_de(c, f"/api/provas?ids={ids[2]},{ids[0]},{ids[0]},{ids[1]}&formato=json")
        self.assertEqual([r["pergunta_id"] for r in pedido["registros"]], [ids[2], ids[0], ids[1]])
        self.assertEqual([r["pergunta"] for r in pedido["registros"]], ["Pergunta 2?", "Pergunta 0?", "Pergunta 1?"])
        # cada registro carrega o próprio trecho
        self.assertEqual([r["trechos"][0]["trecho"] for r in doc["registros"]], [f"{TRECHO} #{i}" for i in range(3)])

    def test_zip_do_dossie_tem_um_arquivo_de_trecho_por_consulta(self):
        c = self.cliente_com_plano()
        ids = self.tres(c)
        z, pasta = self.abrir_zip(self.baixar(c, f"/api/provas?ids={ids[0]},{ids[1]}")[2])
        self.assertEqual(sorted(n for n in z.namelist() if n.startswith("trechos/")), [f"trechos/{ids[0]}-1.txt", f"trechos/{ids[1]}-1.txt"])
        r = verificar(pasta)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_id_inexistente_no_dossie_recusa_tudo(self):
        c = self.cliente_com_plano()
        ids = self.tres(c)
        self.assertEqual(self.baixar(c, f"/api/provas?ids={ids[0]},99999999")[0], 404)

    def test_so_a_conta_do_dono_entra_no_dossie(self):
        a, b = self.cliente_com_plano(), self.cliente_com_plano()
        self.tres(a)
        pid_b = self.completa(b)
        doc = self.json_de(b, "/api/provas?formato=json")
        self.assertEqual([r["pergunta_id"] for r in doc["registros"]], [pid_b])


class TestSemSegredo(Prova):
    def test_arquivo_exportado_nao_tem_segredo_chave_nem_caminho_interno(self):
        c = self.cliente_com_plano()
        config = (RAIZ / "site" / "hackathon-config.php").read_text(encoding="utf-8")
        segredos = [x for x in (WORKER_KEY, c.cookie_sessao(), c.csrf) if x]
        segredos += re.findall(r"const (?:DB_PASS|API_KEY) = '([^']{6,})'", config)
        # o worker (ou um dado malformado) tenta passar caminho do servidor, chave e campos desconhecidos
        sujo = fonte(arquivo=r"C:\Users\Rodri\Desktop\Hackathon\hackathon\dados\bruto\contratos-2024.html")
        sujo["dados"].update({"chave_api": "sk-NAO-PODE-APARECER-123456789", "caminho_interno": "/var/www/hackathon/dados/bruto/x.html"})
        pid = self.responder(c, [sujo, {"tipo": "texto", "dados": {"delta": "Resposta."}}, fim(**MODELO, DEEPSEEK_API_KEY="sk-NAO-PODE-APARECER-123456789")])
        status, _, dados = self.baixar(c, f"/api/perguntas/{pid}/prova")
        self.assertEqual(status, 200)
        z = zipfile.ZipFile(io.BytesIO(dados))
        tudo = dados + b"\n".join(z.read(n) for n in z.namelist())
        for segredo in segredos:
            self.assertTrue(segredo and segredo.encode() not in tudo, "segredo no pacote")
        texto = tudo.decode("utf-8", errors="replace")
        self.assertNotIn("sk-NAO-PODE", texto)
        self.assertNotIn("chave_api", texto)
        self.assertNotIn("caminho_interno", texto)
        self.assertNotRegex(texto, r"[A-Za-z]:\\|/var/www|/home/|hackathon-config|C:/Users")
        self.assertEqual(json.loads(z.read("prova.json"))["registros"][0]["trechos"][0]["arquivo_bruto"], "contratos-2024.html")


def php_executar(codigo: str) -> str:
    """Roda um trecho de PHP carregando só o lib_prova.php (sem banco), para testar uma função isolada."""
    lib = str(RAIZ / "site/public_html/api/lib_prova.php").replace("\\", "/")
    r = subprocess.run([PHP, "-r", f'define("API", true); require "{lib}"; {codigo}'], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


class TestCorrecoes(Prova):
    # ---- B.2 byte inválido ----
    def test_byte_invalido_no_trecho_vira_substituicao_e_o_verificador_passa(self):
        saida = php_executar(r'''
            $sujo = "Valor R\xC3( 10 e \xFF fim";           // dois bytes inválidos em UTF-8
            [$t] = prova_trecho(["trecho" => $sujo, "url" => "https://p.exemplo", "capturado_em" => "2026-11-05", "arquivo" => "a.html",
                                 "tabela" => "t", "linha" => 1, "documento_hash" => str_repeat("a", 64), "hash_confere" => true, "evidencia" => "e1"], "trechos/1-1.txt");
            $reg = ["pergunta_id" => 1, "pergunta" => "Q?", "prova" => "com_prova", "motivo_prova" => null, "trechos" => [$t]];
            [$json, $arquivos] = prova_pacote([$reg], false);
            echo json_encode(array_map("base64_encode", $arquivos));''')
        import base64
        arquivos = {n: base64.b64decode(v) for n, v in json.loads(saida).items()}     # o pacote saiu, sem exceção
        pasta = Path(tempfile.mkdtemp(prefix="invalido-"))
        for nome, dados in arquivos.items():
            (pasta / nome).parent.mkdir(parents=True, exist_ok=True)
            (pasta / nome).write_bytes(dados)
        doc = json.loads(arquivos["prova.json"].decode("utf-8"))                              # JSON final continua válido
        trecho = doc["registros"][0]["trechos"][0]["trecho"]
        self.assertEqual(trecho, "Valor R�( 10 e � fim")
        self.assertEqual(arquivos["trechos/1-1.txt"].decode("utf-8"), trecho)                 # o arquivo do trecho usa o mesmo texto
        self.assertEqual(hashlib.sha256(arquivos["trechos/1-1.txt"]).hexdigest(), doc["registros"][0]["trechos"][0]["trecho_sha256"])
        r = verificar(pasta)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_json_final_com_byte_invalido_solto_tambem_nao_derruba(self):
        saida = php_executar(r'''
            $reg = ["pergunta_id" => 1, "pergunta" => "Q\xC3?", "prova" => "sem_prova", "motivo_prova" => "m\xFF", "trechos" => []];
            [$json] = prova_pacote([$reg], false);
            echo $json;''')
        self.assertIn("�", json.loads(saida)["registros"][0]["motivo_prova"])

    # ---- B.3 ----
    def test_dados_pessoais_nunca_sai_como_falso(self):
        c = self.cliente_com_plano()
        for pid in (self.completa(c), self.responder(c, [{"tipo": "texto", "dados": {"delta": "x"}}, fim()], "Outra?")):
            perfil = self.json_de(c, f"/api/perguntas/{pid}/prova?formato=json")["registros"][0]["perfil"]
            self.assertIsNone(perfil["dados_pessoais"])
            self.assertIn("não afirma", perfil["dados_pessoais_nota"])
        _, pasta = self.abrir_zip(self.baixar(c, f"/api/perguntas/{pid}/prova")[2])
        self.assertIn("dados_pessoais", (pasta / "LEIA-ME.txt").read_text(encoding="utf-8"))

    # ---- C.1 ----
    def test_hash_confere_aceita_true_e_1_e_nada_alem(self):
        c = self.cliente_com_plano()
        # lista (e não dict): True e 1 são a mesma chave em Python. Só o booleano true e o inteiro 1 valem.
        esperado = [(True, "com_prova"), (1, "com_prova"), ("true", "prova_incompleta"), (2, "prova_incompleta"), (0, "prova_incompleta"),
                    (False, "prova_incompleta"), (None, "prova_incompleta"), ("1", "prova_incompleta"), ([1], "prova_incompleta"),
                    (1.0, "com_prova")]   # a API do site normaliza 1.0 para 1 ao gravar (json_encode do PHP), então chega como inteiro
        for valor, prova in esperado:
            pid = self.responder(c, [fonte(hash_confere=valor), {"tipo": "texto", "dados": {"delta": "R."}}, fim()])
            r = self.json_de(c, f"/api/perguntas/{pid}/prova?formato=json")["registros"][0]
            self.assertEqual(r["prova"], prova, repr(valor))
            self.assertEqual(r["trechos"][0]["hash_conferido_na_consulta"], prova == "com_prova", repr(valor))

    # ---- C.2 ----
    def semear(self, c, n):
        uid = sql(f"SELECT id FROM usuarios WHERE email = '{c.email}'")
        valores = ",".join(f"({uid}, {plano_unico()}, 'Pergunta {i}?', '[\"pe-estado\"]', 'concluida')" for i in range(n))
        sql(f"INSERT INTO perguntas (usuario_id, plano_id, texto, tenants, status) VALUES {valores}")
        dados = json.dumps(fonte()["dados"], ensure_ascii=False).replace("'", "''")
        for seq, tipo, d in ((1, "fonte", dados), (2, "texto", '{"delta": "R."}'), (3, "fim", '{"duracao_ms": 1}')):
            sql(f"INSERT INTO eventos (pergunta_id, seq, tipo, dados) SELECT id, {seq}, '{tipo}', '{d}' FROM perguntas WHERE usuario_id = {uid}")
        return n

    def test_dossie_nao_faz_uma_consulta_por_pedido(self):
        """Com N+1 seriam ~2 consultas por id (60 para 30 ids). Agora são 2 no total, mais as de sessão e o ruído de workers
        reais consultando o mesmo banco (uma dezena por segundo)."""
        c = self.cliente_com_plano()
        n = self.semear(c, 30)
        contar = lambda: int(sql("SHOW GLOBAL STATUS LIKE 'Questions'").split()[1])  # noqa: E731
        melhor = None
        for _ in range(3):
            antes = contar()
            doc = self.json_de(c, "/api/provas?formato=json")
            gastas = contar() - antes - 1
            melhor = gastas if melhor is None else min(melhor, gastas)
            self.assertEqual(len(doc["registros"]), n)
        self.assertLess(melhor, 30, f"{melhor} consultas ao banco para {n} pedidos")

    # ---- C.3 ----
    def test_pacote_grande_demais_recusa_com_mensagem_e_sem_arquivo(self):
        c = self.cliente_com_plano()
        pid = self.criar_em_processamento(c, "Resposta gigante?")
        enorme = "x" * 19000                         # perto do teto de 20 mil bytes por evento
        seq = 0
        for _ in range(4):                           # 4 lotes de 40 trechos (o corpo de um lote é limitado a 1 MB)
            lote = []
            for _ in range(40):
                seq += 1
                lote.append({"seq": seq, **fonte(evidencia=f"g:{seq}", linha=seq, trecho=enorme)})
            self.assertEqual(worker(self.base, "POST", f"/api/worker/perguntas/{pid}/eventos", {"eventos": lote}).status, 200)
        w = worker(self.base, "POST", f"/api/worker/perguntas/{pid}/eventos", {"eventos": [{"seq": seq + 1, **fim()}]})
        self.assertEqual(w.status, 200)
        for formato in ("zip", "json"):
            status, cab, corpo = self.baixar(c, f"/api/perguntas/{pid}/prova?formato={formato}")
            self.assertEqual(status, 422, formato)
            self.assertTrue(cab["Content-Type"].startswith("application/json"))
            self.assertNotIn("Content-Disposition", cab)
            msg = json.loads(corpo)["erro"]
            self.assertIn("Pacote grande demais", msg)
            self.assertIn("limite é 5 MB", msg)
            self.assertIn("Reduza o número de consultas", msg)

    # ---- C.4 ----
    def pacote_aberto(self, c):
        pid = self.completa(c)
        return self.abrir_zip(self.baixar(c, f"/api/perguntas/{pid}/prova")[2])[1]

    def test_verificador_sem_pasta_de_brutos_funciona_e_avisa_que_a_origem_nao_foi_conferida(self):
        pasta = self.pacote_aberto(self.cliente_com_plano())
        for args in ((), ("--bruto",)):                      # sem a opção, e a opção sem a pasta (antes dava IndexError)
            r = verificar(pasta, *args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertIn("NÃO CONFERIDO", r.stdout)
            self.assertIn("ATENÇÃO: a origem de 1 trecho(s) NÃO foi conferida", r.stdout)

    def test_verificador_usa_a_pasta_bruto_ao_lado_dele_por_padrao(self):
        pasta = self.pacote_aberto(self.cliente_com_plano())
        (pasta / "bruto").mkdir()
        (pasta / "bruto" / "contratos-2024.html").write_bytes(b"arquivo bruto de mentira")
        for args in ((), ("--bruto",)):
            r = verificar(pasta, *args)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("contratos-2024.html: CONFERE", r.stdout)
            self.assertNotIn("ATENÇÃO", r.stdout)
        (pasta / "bruto" / "contratos-2024.html").write_bytes(b"adulterado")
        self.assertEqual(verificar(pasta).returncode, 1)

    def test_leia_me_explica_o_que_nao_da_para_verificar_sem_o_bruto(self):
        pasta = self.pacote_aberto(self.cliente_com_plano())
        leia = (pasta / "LEIA-ME.txt").read_text(encoding="utf-8")
        self.assertIn("A pasta é opcional", leia)
        self.assertIn("NÃO foi conferida", leia)
        self.assertIn("5 MB", leia)

    # ---- C.5 ----
    def test_resposta_vazia_com_trecho_nao_sai_como_com_prova(self):
        c = self.cliente_com_plano()
        for eventos in ([fonte(), fim()], [fonte(), {"tipo": "texto", "dados": {"delta": "   \n "}}, fim()]):
            pid = self.responder(c, eventos)
            r = self.json_de(c, f"/api/perguntas/{pid}/prova?formato=json")["registros"][0]
            self.assertEqual(r["prova"], "sem_prova")
            self.assertIn("sem texto de resposta", r["motivo_prova"])
            self.assertIsNone(r["resposta"])
            self.assertEqual(len(r["trechos"]), 1)          # o trecho que existiu continua listado, só não "prova" nada

    def test_resposta_com_texto_e_trecho_continua_com_prova(self):
        c = self.cliente_com_plano()
        r = self.json_de(c, f"/api/perguntas/{self.completa(c)}/prova?formato=json")["registros"][0]
        self.assertEqual(r["prova"], "com_prova")


if __name__ == "__main__":
    unittest.main()
