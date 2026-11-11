"""Testes da API contra PHP e MariaDB de verdade. Cobrem os critérios de aceite de A01 a A07 da tasks.md.

    docker compose -f site/dev/docker-compose.yml up -d
    php site/setup.php                      # tabelas e planos
    python site/dev/test_api.py             # PHP_BIN=/caminho/php.exe se o php não estiver no PATH

Os testes sobem os próprios servidores PHP (em portas livres) e limpam o que criam. Só usam a biblioteca padrão.
"""

import http.cookiejar
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PHP = os.environ.get("PHP_BIN") or shutil.which("php")
CONTAINER = os.environ.get("DB_CONTAINER", "hackathon-site-db")
CONFIG = (RAIZ / "site" / "hackathon-config.php").read_text(encoding="utf-8")
WORKER_KEY = re.search(r"const WORKER_KEY = '([^']+)'", CONFIG).group(1)
SERVIDORES: list[tuple[subprocess.Popen, str]] = []


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sql(consulta: str) -> str:
    r = subprocess.run(["docker", "exec", CONTAINER, "mariadb", "-uroot", "-pdev-root", "hackathon", "-N", "-B", "-e", consulta],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"SQL falhou: {r.stderr.strip()}")
    return r.stdout.strip()


_PLANOS = {}


def plano_unico() -> int:
    """Id do plano de verdade (R$ 149). Não use um número fixo: o id depende do que o banco já viu."""
    if "unico" not in _PLANOS:
        _PLANOS["unico"] = int(sql("SELECT id FROM planos WHERE nome NOT LIKE 'Teste %' ORDER BY id LIMIT 1"))
    return _PLANOS["unico"]


def plano_garanhuns() -> int:
    """Plano só de teste, com um único ente, para provar que cada pergunta copia os entes do plano da conta.
    Existe só durante os testes; o tearDownModule o remove."""
    # o setup.php apaga planos que não são os oficiais, então confere se ele ainda existe antes de usar o id guardado
    if "garanhuns" in _PLANOS and sql(f"SELECT COUNT(*) FROM planos WHERE id={_PLANOS['garanhuns']}") != "1":
        del _PLANOS["garanhuns"]
    if "garanhuns" not in _PLANOS:
        sql("INSERT INTO planos (nome, preco_mensal, franquia, preco_excedente, tenants) "
            "VALUES ('Teste so Garanhuns', 1, 0, 0, '[\"pe-garanhuns\"]') ON DUPLICATE KEY UPDATE tenants=VALUES(tenants)")
        _PLANOS["garanhuns"] = int(sql("SELECT id FROM planos WHERE nome='Teste so Garanhuns'"))
    return _PLANOS["garanhuns"]


def remover_planos_de_teste():
    sql("DELETE FROM perguntas WHERE plano_id IN (SELECT id FROM planos WHERE nome LIKE 'Teste %'); "
        "DELETE FROM assinaturas WHERE plano_id IN (SELECT id FROM planos WHERE nome LIKE 'Teste %'); "
        "DELETE FROM planos WHERE nome LIKE 'Teste %'")


def setUpModule():
    remover_planos_de_teste()
    assert PHP, "php não encontrado: defina PHP_BIN"
    for _ in range(3):
        porta = porta_livre()
        p = subprocess.Popen([PHP, "-S", f"127.0.0.1:{porta}", "-t", str(RAIZ / "site/public_html"), str(RAIZ / "site/dev/router.php")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        SERVIDORES.append((p, f"http://127.0.0.1:{porta}"))
    for _, base in SERVIDORES:
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/api/saude", timeout=2).read()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError(f"servidor {base} não subiu")


def tearDownModule():
    for p, _ in SERVIDORES:
        p.terminate()
    sql("DELETE FROM perguntas; DELETE FROM tentativas_login; DELETE FROM usuarios WHERE email LIKE '%@teste.local'")
    remover_planos_de_teste()


class Resposta:
    def __init__(self, status, corpo, cabecalhos):
        self.status, self.corpo, self.cabecalhos = status, corpo, cabecalhos

    def __getitem__(self, chave):
        return self.corpo[chave]


def chamar(base, metodo, caminho, corpo=None, cabecalhos=None, opener=None, bruto=None) -> Resposta:
    dados = bruto if bruto is not None else (json.dumps(corpo).encode() if corpo is not None else None)
    cab = {"Content-Type": "application/json", **(cabecalhos or {})}
    req = urllib.request.Request(base + caminho, data=dados, method=metodo, headers=cab)
    try:
        r = (opener or urllib.request.build_opener()).open(req, timeout=15)
    except urllib.error.HTTPError as e:
        r = e
    texto = r.read().decode("utf-8")
    try:
        parsed = json.loads(texto) if texto else None
    except ValueError:
        parsed = texto
    return Resposta(r.status if hasattr(r, "status") else r.code, parsed, r.headers)


class Cliente:
    """Um navegador: guarda o cookie de sessão e manda o token CSRF."""

    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None

    def req(self, metodo, caminho, corpo=None, csrf=True, token=None):
        cab = {}
        if csrf:
            if self.csrf is None:
                self.me()
            cab["X-CSRF-Token"] = token if token is not None else self.csrf
        r = chamar(self.base, metodo, caminho, corpo, cab, self.opener)
        if isinstance(r.corpo, dict) and r.corpo.get("csrf"):
            self.csrf = r.corpo["csrf"]
        return r

    def me(self):
        r = chamar(self.base, "GET", "/api/me", opener=self.opener)
        self.csrf = r["csrf"]
        return r

    def cookie_sessao(self):
        return next((c.value for c in self.jar if c.name == "hsid"), None)

    def cadastrar(self, email=None, senha="senha-segura-123", nome="Pessoa Teste"):
        email = email or f"{uuid.uuid4().hex[:10]}@teste.local"
        r = self.req("POST", "/api/cadastro", {"nome": nome, "email": email, "senha": senha})
        assert r.status == 201, (r.status, r.corpo)
        self.email, self.senha = email, senha
        return r

    def assinar(self, plano_id=None):
        r = self.req("POST", "/api/assinatura", {"plano_id": plano_id or plano_unico()})
        assert r.status == 201, (r.status, r.corpo)
        return r

    def perguntar(self, texto="O que sabemos sobre o fornecedor?"):
        return self.req("POST", "/api/perguntas", {"texto": texto})


def worker(base, metodo, caminho, corpo=None, chave=WORKER_KEY):
    return chamar(base, metodo, caminho, corpo, {"X-Worker-Key": chave} if chave is not None else {})


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = SERVIDORES[0][1]

    def setUp(self):
        sql("DELETE FROM perguntas; DELETE FROM tentativas_login; DELETE FROM telefones")

    def cliente_com_plano(self, plano_id=None):
        c = Cliente(self.base)
        c.cadastrar()
        c.assinar(plano_id or plano_unico())
        return c

    def concluir(self, pergunta_id, tipo="fim"):
        r = worker(self.base, "POST", "/api/worker/proxima")
        self.assertEqual(r.status, 200, r.corpo)
        w = worker(self.base, "POST", f"/api/worker/perguntas/{r['id']}/eventos", {"eventos": [{"seq": 1, "tipo": tipo, "dados": {}}]})
        self.assertEqual(w.status, 200, w.corpo)


class TestA01Banco(Base):
    def test_tabelas_e_planos_existem(self):
        tabelas = set(sql("SHOW TABLES").split())
        self.assertTrue({"usuarios", "planos", "assinaturas", "telefones", "perguntas", "eventos", "tentativas_login"} <= tabelas)
        self.assertEqual(sql("SELECT COUNT(*) FROM planos WHERE nome NOT LIKE 'Teste %'"), "1")

    def test_setup_repetido_nao_duplica(self):
        antes = sql("SELECT COUNT(*) FROM planos")
        subprocess.run([PHP, str(RAIZ / "site/setup.php")], check=True, capture_output=True)
        self.assertEqual(sql("SELECT COUNT(*) FROM planos"), antes)

    def test_setup_move_quem_estava_nos_planos_antigos_para_o_plano_unico(self):
        # Banco antigo: dois planos, com uma assinatura e uma pergunta em um deles. O setup leva tudo para o plano único
        # e apaga os antigos, sem violar as chaves estrangeiras.
        sql("INSERT INTO planos (nome, preco_mensal, franquia, preco_excedente, tenants) VALUES "
            "('Antigo A', 990, 300, 1.5, '[\"pe-garanhuns\"]'), ('Antigo B', 1990, 1000, 1.5, '[\"pe-estado\",\"pe-garanhuns\"]')")
        antigo = int(sql("SELECT id FROM planos WHERE nome='Antigo B'"))
        c = Cliente(self.base); c.cadastrar(); c.assinar(antigo)
        pid = c.perguntar()["id"]
        self.assertEqual(sql(f"SELECT plano_id FROM perguntas WHERE id={pid}"), str(antigo))
        saida = subprocess.run([PHP, str(RAIZ / "site/setup.php")], check=True, capture_output=True, text=True, encoding="utf-8").stdout
        self.assertIn("planos antigos removidos", saida)
        self.assertEqual(sql("SELECT COUNT(*) FROM planos WHERE nome LIKE 'Antigo %'"), "0")
        self.assertEqual(c.me()["plano"]["nome"], "Único")
        self.assertEqual(sql(f"SELECT plano_id FROM perguntas WHERE id={pid}"), str(plano_unico()))
        self.assertEqual(json.loads(sql(f"SELECT tenants FROM perguntas WHERE id={pid}")), ["pe-estado", "pe-garanhuns"])

    def test_setup_recusa_rodar_pela_web(self):
        r = chamar(self.base, "GET", "/setup.php")
        self.assertEqual(r.status, 404)


class TestA02Cadastro(Base):
    def test_conta_criada_entra_e_aparece_no_me(self):
        c = Cliente(self.base)
        r = c.cadastrar(nome="Maria")
        self.assertEqual(r["usuario"]["nome"], "Maria")
        me = c.me()
        self.assertEqual(me["usuario"]["email"], c.email)
        self.assertEqual(me["usuario"]["papel"], "usuario")
        self.assertIsNone(me["plano"])

    def test_email_repetido_recebe_erro(self):
        a = Cliente(self.base); a.cadastrar(email="repetido@teste.local")
        b = Cliente(self.base)
        r = b.req("POST", "/api/cadastro", {"nome": "Outra", "email": "REPETIDO@teste.local", "senha": "senha-segura-123"})
        self.assertEqual(r.status, 409)
        self.assertIn("e-mail", r["erro"])

    def test_dados_invalidos(self):
        c = Cliente(self.base)
        casos = [
            {"nome": "", "email": "a@teste.local", "senha": "senha-segura-123"},
            {"nome": "x", "email": "isto-nao-e-email", "senha": "senha-segura-123"},
            {"nome": "x", "email": "a@teste.local", "senha": "curta"},
            {"nome": "x", "email": "a@teste.local", "senha": "s" * 73},
            {"nome": "x" * 121, "email": "a@teste.local", "senha": "senha-segura-123"},
            {"nome": 123, "email": "a@teste.local", "senha": "senha-segura-123"},
        ]
        for corpo in casos:
            self.assertEqual(c.req("POST", "/api/cadastro", corpo).status, 400, corpo)

    def test_senha_nao_e_guardada_em_texto(self):
        c = Cliente(self.base); c.cadastrar(senha="segredo-bem-guardado")
        guardado = sql(f"SELECT senha_hash FROM usuarios WHERE email='{c.email}'")
        self.assertTrue(guardado.startswith("$2y$"))
        self.assertNotIn("segredo-bem-guardado", guardado)

    def test_json_invalido_recebe_400(self):
        c = Cliente(self.base); c.me()
        r = chamar(self.base, "POST", "/api/cadastro", bruto=b"{isto nao e json", cabecalhos={"X-CSRF-Token": c.csrf}, opener=c.opener)
        self.assertEqual(r.status, 400)


class TestA03Login(Base):
    def test_login_certo_e_logout(self):
        c = Cliente(self.base); c.cadastrar()
        c.req("POST", "/api/logout")
        self.assertIsNone(c.me()["usuario"])
        r = c.req("POST", "/api/login", {"email": c.email, "senha": c.senha})
        self.assertEqual(r.status, 200)
        self.assertEqual(c.me()["usuario"]["email"], c.email)

    def test_erro_de_login_nao_diz_qual_campo_falhou(self):
        c = Cliente(self.base); c.cadastrar()
        outro = Cliente(self.base)
        senha_errada = outro.req("POST", "/api/login", {"email": c.email, "senha": "senha-errada-123"})
        sem_conta = outro.req("POST", "/api/login", {"email": "ninguem@teste.local", "senha": "senha-errada-123"})
        self.assertEqual((senha_errada.status, sem_conta.status), (401, 401))
        self.assertEqual(senha_errada["erro"], sem_conta["erro"])

    def test_csrf_ausente_ou_errado_recebe_403(self):
        c = Cliente(self.base); c.cadastrar()
        for metodo, caminho, corpo in [("POST", "/api/login", {"email": "a@teste.local", "senha": "x"}),
                                       ("POST", "/api/cadastro", {"nome": "x", "email": "b@teste.local", "senha": "senha-segura-123"}),
                                       ("POST", "/api/logout", None), ("POST", "/api/assinatura", {"plano_id": plano_unico()}),
                                       ("POST", "/api/perguntas", {"texto": "oi"})]:
            self.assertEqual(c.req(metodo, caminho, corpo, csrf=False).status, 403, f"sem token: {caminho}")
            self.assertEqual(c.req(metodo, caminho, corpo, token="token-falso").status, 403, f"token falso: {caminho}")

    def test_csrf_de_outra_sessao_nao_vale(self):
        a = Cliente(self.base); a.cadastrar()
        b = Cliente(self.base); b.cadastrar()
        self.assertEqual(b.req("POST", "/api/assinatura", {"plano_id": plano_unico()}, token=a.csrf).status, 403)

    def test_tentativas_seguidas_sao_limitadas(self):
        c = Cliente(self.base); c.cadastrar()
        outro = Cliente(self.base)
        for _ in range(5):
            self.assertEqual(outro.req("POST", "/api/login", {"email": c.email, "senha": "errada-errada"}).status, 401)
        r = outro.req("POST", "/api/login", {"email": c.email, "senha": c.senha})   # até a senha certa é barrada
        self.assertEqual(r.status, 429)
        self.assertEqual(r.cabecalhos.get("Retry-After"), "900")

    def test_login_certo_zera_as_falhas(self):
        c = Cliente(self.base); c.cadastrar()
        outro = Cliente(self.base)
        for _ in range(3):
            outro.req("POST", "/api/login", {"email": c.email, "senha": "errada-errada"})
        self.assertEqual(outro.req("POST", "/api/login", {"email": c.email, "senha": c.senha}).status, 200)
        self.assertEqual(sql(f"SELECT COUNT(*) FROM tentativas_login WHERE email='{c.email}'"), "0")

    def test_injecao_de_sql_no_login(self):
        c = Cliente(self.base)
        for email in ["' OR '1'='1", "x@teste.local' --", "a@teste.local\" OR 1=1 #"]:
            r = c.req("POST", "/api/login", {"email": email, "senha": "' OR '1'='1"})
            self.assertIn(r.status, (401, 429), email)
        self.assertIsNone(c.me()["usuario"])

    def test_sessao_muda_no_login_e_cookie_e_httponly(self):
        c = Cliente(self.base)
        r = chamar(self.base, "GET", "/api/me", opener=c.opener)
        self.assertTrue(any("HttpOnly" in h and "SameSite=Lax" in h for h in r.cabecalhos.get_all("Set-Cookie")), r.cabecalhos.get_all("Set-Cookie"))
        c.csrf = r["csrf"]
        antes = c.cookie_sessao()
        c.cadastrar()
        self.assertNotEqual(antes, c.cookie_sessao())   # fixação de sessão

    def test_conta_apagada_derruba_a_sessao(self):
        c = Cliente(self.base); c.cadastrar()
        sql(f"DELETE FROM usuarios WHERE email='{c.email}'")
        self.assertIsNone(c.me()["usuario"])


class TestA04Planos(Base):
    def test_lista_publica_com_entes(self):
        r = chamar(self.base, "GET", "/api/planos")
        self.assertEqual(r.status, 200)
        # só o plano de verdade: os "Teste ..." existem apenas enquanto um teste os cria
        reais = [p for p in r.corpo if not p["nome"].startswith("Teste ")]
        self.assertEqual([p["nome"] for p in reais], ["Único"])
        unico = reais[0]
        self.assertEqual(unico["tenants"], ["pe-estado", "pe-garanhuns"])
        self.assertEqual((unico["preco_mensal"], unico["franquia"], unico["preco_excedente"]), (149.0, 0, 0.0))

    def test_ativa_sem_pagamento_e_me_mostra_o_plano(self):
        c = Cliente(self.base); c.cadastrar()
        r = c.req("POST", "/api/assinatura", {"plano_id": plano_unico()})
        self.assertEqual(r.status, 201)
        self.assertEqual(c.me()["plano"]["nome"], "Único")

    def test_trocar_de_plano_deixa_uma_so_ativa(self):
        c = self.cliente_com_plano(plano_garanhuns())
        self.assertEqual(c.me()["plano"]["nome"], "Teste so Garanhuns")
        c.assinar(plano_unico())
        self.assertEqual(c.me()["plano"]["nome"], "Único")
        self.assertEqual(sql(f"SELECT COUNT(*) FROM assinaturas a JOIN usuarios u ON u.id=a.usuario_id WHERE u.email='{c.email}' AND a.status='ativa'"), "1")

    def test_assinar_de_novo_o_mesmo_plano_continua_com_uma_so_ativa(self):
        c = self.cliente_com_plano()
        c.assinar()
        self.assertEqual(sql(f"SELECT COUNT(*) FROM assinaturas a JOIN usuarios u ON u.id=a.usuario_id WHERE u.email='{c.email}' AND a.status='ativa'"), "1")

    def test_assinatura_exige_login_e_plano_valido(self):
        anon = Cliente(self.base); anon.me()
        self.assertEqual(anon.req("POST", "/api/assinatura", {"plano_id": plano_unico()}).status, 401)
        c = Cliente(self.base); c.cadastrar()
        self.assertEqual(c.req("POST", "/api/assinatura", {"plano_id": 99999999}).status, 404)
        for ruim in ["1", None, 0, -1, 1.5, [1]]:
            self.assertEqual(c.req("POST", "/api/assinatura", {"plano_id": ruim}).status, 400, ruim)


class TestA05Perguntas(Base):
    def test_exige_login_e_plano(self):
        anon = Cliente(self.base); anon.me()
        self.assertEqual(anon.perguntar().status, 401)
        sem_plano = Cliente(self.base); sem_plano.cadastrar()
        r = sem_plano.perguntar()
        self.assertEqual(r.status, 403)
        self.assertIn("plano", r["erro"])

    def test_copia_os_entes_do_plano(self):
        for plano_id, esperado in [(plano_garanhuns(), ["pe-garanhuns"]), (plano_unico(), ["pe-estado", "pe-garanhuns"])]:
            sql("DELETE FROM perguntas")
            c = self.cliente_com_plano(plano_id)
            pid = c.perguntar()["id"]
            self.assertEqual(json.loads(sql(f"SELECT tenants FROM perguntas WHERE id={pid}")), esperado)

    def test_segunda_pergunta_aberta_recebe_409(self):
        c = self.cliente_com_plano()
        primeira = c.perguntar()
        segunda = c.perguntar("outra")
        self.assertEqual((primeira.status, segunda.status), (201, 409))
        self.assertEqual(segunda["pergunta_id"], primeira["id"])
        self.assertEqual(c.req("GET", "/api/perguntas/aberta", csrf=False)["pergunta"]["id"], primeira["id"])

    def test_pode_perguntar_de_novo_depois_de_terminar(self):
        c = self.cliente_com_plano()
        c.perguntar()
        self.concluir(None)
        self.assertEqual(c.perguntar("segunda").status, 201)

    def test_tamanho_da_pergunta(self):
        c = self.cliente_com_plano()
        self.assertEqual(c.perguntar("x" * 501).status, 400)
        self.assertEqual(c.perguntar("").status, 400)
        self.assertEqual(c.perguntar("   ").status, 400)
        self.assertEqual(c.req("POST", "/api/perguntas", {"texto": 123}).status, 400)
        self.assertEqual(c.perguntar("á" * 500).status, 201)   # 500 caracteres (1000 bytes) valem

    def test_duas_requisicoes_ao_mesmo_tempo_abrem_so_uma(self):
        # Seis sessões diferentes da mesma conta, em três servidores. Com a mesma sessão o PHP serializaria as
        # requisições (trava o arquivo de sessão) e esconderia a corrida: aqui só o banco protege.
        c = self.cliente_com_plano()
        abas = []
        for i in range(6):
            aba = Cliente(SERVIDORES[i % 3][1])
            self.assertEqual(aba.req("POST", "/api/login", {"email": c.email, "senha": c.senha}).status, 200)
            abas.append(aba)
        # A janela entre "conferir se há pergunta aberta" e "inserir" dura milissegundos, então uma rodada só
        # raramente colide. Repetimos várias vezes: sem a trava no banco, o teste falha de forma confiável.
        for rodada in range(25):
            sql(f"DELETE p FROM perguntas p JOIN usuarios u ON u.id=p.usuario_id WHERE u.email='{c.email}'")
            barreira = threading.Barrier(6)
            status = []

            def disparar(aba, i):
                barreira.wait()
                status.append(aba.perguntar(f"rodada {rodada} pergunta {i}").status)

            ts = [threading.Thread(target=disparar, args=(a, i)) for i, a in enumerate(abas)]
            [t.start() for t in ts]; [t.join() for t in ts]
            self.assertEqual(sorted(status), [201, 409, 409, 409, 409, 409], f"rodada {rodada}")
            self.assertEqual(sql(f"SELECT COUNT(*) FROM perguntas p JOIN usuarios u ON u.id=p.usuario_id WHERE u.email='{c.email}'"), "1", f"rodada {rodada}")

    def test_mudar_de_plano_nao_altera_a_pergunta_em_andamento(self):
        c = self.cliente_com_plano(plano_unico())
        pid = c.perguntar()["id"]
        c.assinar(plano_garanhuns())
        self.assertEqual(json.loads(sql(f"SELECT tenants FROM perguntas WHERE id={pid}")), ["pe-estado", "pe-garanhuns"])

    def test_texto_e_guardado_sem_executar_nada(self):
        c = self.cliente_com_plano()
        pid = c.perguntar("<script>alert(1)</script> '); DROP TABLE perguntas;--")["id"]
        self.assertEqual(sql("SELECT COUNT(*) FROM perguntas"), "1")
        self.assertIn("<script>", sql(f"SELECT texto FROM perguntas WHERE id={pid}"))

    def test_caracteres_de_controle_sao_removidos(self):
        c = self.cliente_com_plano()
        pid = c.perguntar("olá\x00\x07 mundo")["id"]
        self.assertEqual(sql(f"SELECT texto FROM perguntas WHERE id={pid}"), "olá mundo")


class TestA06Eventos(Base):
    def preparar(self):
        c = self.cliente_com_plano()
        pid = c.perguntar()["id"]
        p = worker(self.base, "POST", "/api/worker/proxima")
        self.assertEqual(p["id"], pid)
        eventos = [{"seq": 1, "tipo": "consulta", "dados": {"nome": "cobertura"}},
                   {"seq": 2, "tipo": "texto", "dados": {"delta": "Encontrei "}},
                   {"seq": 3, "tipo": "texto", "dados": {"delta": "um contrato."}}]
        self.assertEqual(worker(self.base, "POST", f"/api/worker/perguntas/{pid}/eventos", {"eventos": eventos}).status, 200)
        return c, pid

    def test_devolve_so_o_que_veio_depois_de_desde(self):
        c, pid = self.preparar()
        tudo = c.req("GET", f"/api/perguntas/{pid}/eventos?desde=0", csrf=False)
        self.assertEqual([e["seq"] for e in tudo["eventos"]], [1, 2, 3])
        self.assertEqual(tudo["status"], "processando")
        resto = c.req("GET", f"/api/perguntas/{pid}/eventos?desde=2", csrf=False)
        self.assertEqual([e["seq"] for e in resto["eventos"]], [3])
        self.assertEqual(resto["eventos"][0]["dados"], {"delta": "um contrato."})
        self.assertEqual(c.req("GET", f"/api/perguntas/{pid}/eventos?desde=3", csrf=False)["eventos"], [])

    def test_outro_usuario_recebe_404(self):
        c, pid = self.preparar()
        intruso = Cliente(self.base); intruso.cadastrar()
        r = intruso.req("GET", f"/api/perguntas/{pid}/eventos", csrf=False)
        self.assertEqual(r.status, 404)
        inexistente = c.req("GET", "/api/perguntas/999999/eventos", csrf=False)
        self.assertEqual(inexistente.status, 404)
        self.assertEqual(r["erro"], inexistente["erro"])   # não confirma que a pergunta existe

    def test_exige_login_e_desde_valido(self):
        c, pid = self.preparar()
        anon = Cliente(self.base)
        self.assertEqual(chamar(self.base, "GET", f"/api/perguntas/{pid}/eventos", opener=anon.opener).status, 401)
        for ruim in ["abc", "-1", "1.5"]:
            self.assertEqual(c.req("GET", f"/api/perguntas/{pid}/eventos?desde={ruim}", csrf=False).status, 400, ruim)

    def test_fim_encerra_e_informa_duracao(self):
        c, pid = self.preparar()
        worker(self.base, "POST", f"/api/worker/perguntas/{pid}/eventos", {"eventos": [{"seq": 4, "tipo": "fim", "dados": {}}]})
        r = c.req("GET", f"/api/perguntas/{pid}/eventos?desde=3", csrf=False)
        self.assertEqual(r["status"], "concluida")
        self.assertEqual(r["eventos"][0]["tipo"], "fim")
        self.assertGreaterEqual(r["duracao_ms"], 0)


class TestA07Worker(Base):
    def test_sem_chave_ou_com_chave_errada_recebe_401(self):
        for chave in [None, "", "chave-errada", WORKER_KEY[:-1], WORKER_KEY + "x"]:
            for metodo, caminho in [("POST", "/api/worker/proxima"), ("GET", "/api/worker/telefones"),
                                    ("POST", "/api/worker/perguntas/1/eventos")]:
                self.assertEqual(worker(self.base, metodo, caminho, {"eventos": []} if metodo == "POST" else None, chave).status, 401, (chave, caminho))

    def test_sessao_de_usuario_nao_serve_de_chave(self):
        c = self.cliente_com_plano()
        self.assertEqual(chamar(self.base, "POST", "/api/worker/proxima", opener=c.opener).status, 401)

    def test_fila_vazia_devolve_204(self):
        self.assertEqual(worker(self.base, "POST", "/api/worker/proxima").status, 204)

    def test_entrega_a_mais_antiga_primeiro_com_os_entes_do_plano(self):
        a, b = self.cliente_com_plano(plano_garanhuns()), self.cliente_com_plano(plano_unico())
        ida, idb = a.perguntar("primeira")["id"], b.perguntar("segunda")["id"]
        p1 = worker(self.base, "POST", "/api/worker/proxima")
        self.assertEqual((p1["id"], p1["texto"], p1["tenants"], p1["ver_pessoal"]), (ida, "primeira", ["pe-garanhuns"], False))
        p2 = worker(self.base, "POST", "/api/worker/proxima")
        self.assertEqual((p2["id"], p2["tenants"]), (idb, ["pe-estado", "pe-garanhuns"]))
        self.assertEqual(worker(self.base, "POST", "/api/worker/proxima").status, 204)
        self.assertEqual(sql(f"SELECT status FROM perguntas WHERE id={ida}"), "processando")

    def test_dois_pedidos_ao_mesmo_tempo_nao_pegam_a_mesma_pergunta(self):
        # 80 perguntas na fila e 12 workers brigando por elas ao mesmo tempo, em três servidores. Cada pergunta
        # precisa sair exatamente uma vez. Sem o UPDATE condicional, aparecem entregas repetidas.
        a = self.cliente_com_plano()
        sql("INSERT INTO perguntas (usuario_id, plano_id, texto, tenants) "
            f"SELECT u.id, {plano_unico()}, CONCAT('p', n.i), '[\"pe-garanhuns\"]' FROM usuarios u JOIN "
            "(" + " UNION ALL ".join(f"SELECT {i} AS i" for i in range(80)) + f") n WHERE u.email='{a.email}'")
        self.assertEqual(sql("SELECT COUNT(*) FROM perguntas WHERE status='fila'"), "80")
        entregues, lock = [], threading.Lock()
        barreira = threading.Barrier(12)

        def trabalhar(i):
            barreira.wait()
            while True:
                r = worker(SERVIDORES[i % 3][1], "POST", "/api/worker/proxima")
                if r.status == 204:
                    return
                with lock:
                    entregues.append(r["id"])

        ts = [threading.Thread(target=trabalhar, args=(i,)) for i in range(12)]
        [t.start() for t in ts]; [t.join() for t in ts]
        repetidas = sorted({i for i in entregues if entregues.count(i) > 1})
        self.assertEqual(repetidas, [], f"perguntas entregues mais de uma vez: {repetidas}")
        self.assertEqual(len(entregues), 80)
        self.assertEqual(sql("SELECT COUNT(*) FROM perguntas WHERE status='processando'"), "80")

    def enviar(self, pid, eventos):
        return worker(self.base, "POST", f"/api/worker/perguntas/{pid}/eventos", {"eventos": eventos})

    def pergunta_em_andamento(self):
        c = self.cliente_com_plano()
        pid = c.perguntar()["id"]
        worker(self.base, "POST", "/api/worker/proxima")
        return c, pid

    def test_seq_repetido_e_ignorado(self):
        c, pid = self.pergunta_em_andamento()
        ev = {"seq": 1, "tipo": "texto", "dados": {"delta": "a"}}
        self.assertEqual(self.enviar(pid, [ev]).corpo["gravados"], 1)
        r = self.enviar(pid, [ev, {"seq": 2, "tipo": "texto", "dados": {"delta": "b"}}])
        self.assertEqual((r["gravados"], r["ignorados"]), (1, 1))
        dentro = self.enviar(pid, [{"seq": 3, "tipo": "texto", "dados": {"delta": "c"}}, {"seq": 3, "tipo": "texto", "dados": {"delta": "outro"}}])
        self.assertEqual((dentro["gravados"], dentro["ignorados"]), (1, 1))
        self.assertEqual(sql(f"SELECT COUNT(*) FROM eventos WHERE pergunta_id={pid}"), "3")
        self.assertEqual(json.loads(sql(f"SELECT dados FROM eventos WHERE pergunta_id={pid} AND seq=3")), {"delta": "c"})   # o primeiro vale

    def test_validacao_dos_eventos(self):
        c, pid = self.pergunta_em_andamento()
        ruins = [[], [{"seq": 0, "tipo": "texto"}], [{"seq": "1", "tipo": "texto"}], [{"seq": 1, "tipo": "invalido"}],
                 [{"seq": 1, "tipo": "texto", "dados": "solto"}], ["nao-e-objeto"], [{"tipo": "texto"}],
                 [{"seq": i, "tipo": "texto"} for i in range(1, 102)]]
        for lote in ruins:
            self.assertEqual(self.enviar(pid, lote).status, 400, str(lote)[:60])
        self.assertEqual(self.enviar(pid, [{"seq": 1, "tipo": "texto", "dados": {"d": "x" * 20001}}]).status, 413)
        self.assertEqual(sql(f"SELECT COUNT(*) FROM eventos WHERE pergunta_id={pid}"), "0")   # nada entrou pela metade
        self.assertEqual(worker(self.base, "POST", "/api/worker/perguntas/999999/eventos", {"eventos": [{"seq": 1, "tipo": "texto"}]}).status, 404)

    def test_fim_e_erro_encerram_a_pergunta(self):
        for tipo, status in [("fim", "concluida"), ("erro", "erro")]:
            sql("DELETE FROM perguntas")
            c, pid = self.pergunta_em_andamento()
            r = self.enviar(pid, [{"seq": 1, "tipo": "texto", "dados": {"delta": "x"}}, {"seq": 2, "tipo": tipo, "dados": {"motivo": "m"}}])
            self.assertEqual(r["status"], status)
            self.assertEqual(sql(f"SELECT status FROM perguntas WHERE id={pid}"), status)
            self.assertNotEqual(sql(f"SELECT duracao_ms FROM perguntas WHERE id={pid}"), "NULL")

    def test_pergunta_encerrada_nao_aceita_evento_novo_mas_aceita_reenvio(self):
        c, pid = self.pergunta_em_andamento()
        lote = [{"seq": 1, "tipo": "texto", "dados": {"delta": "x"}}, {"seq": 2, "tipo": "fim", "dados": {}}]
        self.assertEqual(self.enviar(pid, lote).status, 200)
        reenvio = self.enviar(pid, lote)   # a rede caiu e o worker mandou de novo: tudo bem
        self.assertEqual((reenvio.status, reenvio["gravados"]), (200, 0))
        self.assertEqual(self.enviar(pid, [{"seq": 3, "tipo": "texto", "dados": {}}]).status, 409)

    def test_telefones_aprovados_so_de_quem_tem_plano(self):
        a, b, c = self.cliente_com_plano(plano_garanhuns()), self.cliente_com_plano(plano_unico()), Cliente(self.base)
        c.cadastrar()   # sem plano
        for cli, numero, status in [(a, "5587999990001", "aprovado"), (b, "5587999990002", "aprovado"),
                                    (a, "5587999990003", "pendente"), (b, "5587999990004", "revogado"), (c, "5587999990005", "aprovado")]:
            sql(f"INSERT INTO telefones (usuario_id, numero, status) SELECT id, '{numero}', '{status}' FROM usuarios WHERE email='{cli.email}'")
        r = worker(self.base, "GET", "/api/worker/telefones")
        self.assertEqual({t["numero"]: t["tenants"] for t in r.corpo},
                         {"5587999990001": ["pe-garanhuns"], "5587999990002": ["pe-estado", "pe-garanhuns"]})


def numero_unico() -> str:
    """Celular de teste único, em formato canônico (55 + DDD + 9 + 8 dígitos)."""
    return "5587" + "9" + f"{uuid.uuid4().int % 10**8:08d}"


class TestA08Telefones(Base):
    def test_exige_login_csrf_e_plano(self):
        anon = Cliente(self.base); anon.me()
        self.assertEqual(anon.req("GET", "/api/telefones", csrf=False).status, 401)
        self.assertEqual(anon.req("POST", "/api/telefones", {"numero": numero_unico()}).status, 401)
        self.assertEqual(anon.req("DELETE", "/api/telefones/1").status, 401)
        sem_plano = Cliente(self.base); sem_plano.cadastrar()
        r = sem_plano.req("POST", "/api/telefones", {"numero": numero_unico()})
        self.assertEqual(r.status, 403)
        self.assertIn("plano", r["erro"])
        c = self.cliente_com_plano()
        self.assertEqual(c.req("POST", "/api/telefones", {"numero": numero_unico()}, csrf=False).status, 403)
        self.assertEqual(c.req("DELETE", "/api/telefones/1", csrf=False).status, 403)

    def test_normaliza_o_numero_e_comeca_pendente(self):
        c = self.cliente_com_plano()
        formas = ["(87) 98888-7777", "+55 87 98888-7777", "87988887777", "558788887777", "087 98888-7777", "0055 87 98888-7777"]
        r = c.req("POST", "/api/telefones", {"numero": formas[0]})
        self.assertEqual((r.status, r["numero"], r["status"]), (201, "5587988887777", "pendente"))
        lista = c.req("GET", "/api/telefones", csrf=False)
        self.assertEqual([(t["numero"], t["status"]) for t in lista.corpo], [("5587988887777", "pendente")])
        for forma in formas[1:]:   # qualquer outra forma de escrever o mesmo número é duplicado
            self.assertEqual(c.req("POST", "/api/telefones", {"numero": forma}).status, 409, forma)

    def test_numeros_invalidos_recebem_400(self):
        c = self.cliente_com_plano()
        for ruim in ["", "abc", "123", "(87) 3761-1234", "87 5999-9999", "+1 415 555 2671", "0", "9" * 40,
                     "(00) 99999-9999", "(87) 89999-9999", 5587999990000, None, ["5587999990000"], {"n": 1}]:
            self.assertEqual(c.req("POST", "/api/telefones", {"numero": ruim}).status, 400, repr(ruim))
        self.assertEqual(c.req("POST", "/api/telefones", {}).status, 400)
        self.assertEqual(c.req("GET", "/api/telefones", csrf=False).corpo, [])

    def test_espacos_e_quebra_de_linha_nas_pontas_sao_toleradas(self):
        c = self.cliente_com_plano()
        n = numero_unico()
        r = c.req("POST", "/api/telefones", {"numero": f"  {n}\n"})   # número colado de outro lugar
        self.assertEqual((r.status, r["numero"]), (201, n))

    def test_numero_ja_cadastrado_por_outra_conta_recebe_409_sem_revelar_o_dono(self):
        a, b = self.cliente_com_plano(), self.cliente_com_plano()
        n = numero_unico()
        self.assertEqual(a.req("POST", "/api/telefones", {"numero": n}).status, 201)
        dele = b.req("POST", "/api/telefones", {"numero": n})
        meu = a.req("POST", "/api/telefones", {"numero": n})
        self.assertEqual((dele.status, meu.status), (409, 409))
        self.assertEqual(dele["erro"], meu["erro"])
        self.assertEqual(b.req("GET", "/api/telefones", csrf=False).corpo, [])

    def test_variacao_do_nono_digito_tambem_e_duplicada(self):
        a, b = self.cliente_com_plano(), self.cliente_com_plano()
        com9 = "5587" + "9" + "70000001"
        sem9 = "5587" + "70000001"
        self.assertEqual(a.req("POST", "/api/telefones", {"numero": com9}).status, 201)
        self.assertEqual(b.req("POST", "/api/telefones", {"numero": sem9}).status, 409)

    def test_limite_de_telefones_por_conta(self):
        c = self.cliente_com_plano()
        for _ in range(3):
            self.assertEqual(c.req("POST", "/api/telefones", {"numero": numero_unico()}).status, 201)
        r = c.req("POST", "/api/telefones", {"numero": numero_unico()})
        self.assertEqual(r.status, 400)
        self.assertIn("3", r["erro"])

    def test_limite_vale_com_seis_requisicoes_ao_mesmo_tempo(self):
        c = self.cliente_com_plano()
        abas = []
        for i in range(6):
            aba = Cliente(SERVIDORES[i % 3][1])
            self.assertEqual(aba.req("POST", "/api/login", {"email": c.email, "senha": c.senha}).status, 200)
            abas.append(aba)
        for rodada in range(8):
            sql(f"DELETE t FROM telefones t JOIN usuarios u ON u.id=t.usuario_id WHERE u.email='{c.email}'")
            barreira = threading.Barrier(6)
            status = []

            def disparar(aba):
                barreira.wait()
                status.append(aba.req("POST", "/api/telefones", {"numero": numero_unico()}).status)

            ts = [threading.Thread(target=disparar, args=(a,)) for a in abas]
            [t.start() for t in ts]; [t.join() for t in ts]
            self.assertEqual(sorted(status), [201, 201, 201, 400, 400, 400], f"rodada {rodada}")

    def test_cada_um_ve_so_os_proprios_telefones(self):
        a, b = self.cliente_com_plano(), self.cliente_com_plano()
        na, nb = numero_unico(), numero_unico()
        a.req("POST", "/api/telefones", {"numero": na}); b.req("POST", "/api/telefones", {"numero": nb})
        self.assertEqual([t["numero"] for t in a.req("GET", "/api/telefones", csrf=False).corpo], [na])
        self.assertEqual([t["numero"] for t in b.req("GET", "/api/telefones", csrf=False).corpo], [nb])

    def test_remover_o_proprio_telefone(self):
        c = self.cliente_com_plano()
        tid = c.req("POST", "/api/telefones", {"numero": numero_unico()})["id"]
        self.assertEqual(c.req("DELETE", f"/api/telefones/{tid}").status, 204)
        self.assertEqual(c.req("GET", "/api/telefones", csrf=False).corpo, [])
        self.assertEqual(c.req("DELETE", f"/api/telefones/{tid}").status, 404)   # já removido

    def test_nao_remove_telefone_de_outra_conta(self):
        a, intruso = self.cliente_com_plano(), self.cliente_com_plano()
        tid = a.req("POST", "/api/telefones", {"numero": numero_unico()})["id"]
        inexistente = intruso.req("DELETE", "/api/telefones/999999")
        r = intruso.req("DELETE", f"/api/telefones/{tid}")
        self.assertEqual((r.status, inexistente.status), (404, 404))
        self.assertEqual(r["erro"], inexistente["erro"])   # não confirma que o telefone existe
        self.assertEqual(len(a.req("GET", "/api/telefones", csrf=False).corpo), 1)

    def test_numero_removido_pode_ser_cadastrado_por_outra_conta(self):
        a, b = self.cliente_com_plano(), self.cliente_com_plano()
        n = numero_unico()
        tid = a.req("POST", "/api/telefones", {"numero": n})["id"]
        a.req("DELETE", f"/api/telefones/{tid}")
        self.assertEqual(b.req("POST", "/api/telefones", {"numero": n}).status, 201)

    def test_remover_aprovado_tira_o_numero_da_lista_do_worker(self):
        c = self.cliente_com_plano(plano_unico())
        n = numero_unico()
        tid = c.req("POST", "/api/telefones", {"numero": n})["id"]
        sql(f"UPDATE telefones SET status='aprovado' WHERE id={tid}")
        self.assertIn(n, [t["numero"] for t in worker(self.base, "GET", "/api/worker/telefones").corpo])
        c.req("DELETE", f"/api/telefones/{tid}")
        self.assertNotIn(n, [t["numero"] for t in worker(self.base, "GET", "/api/worker/telefones").corpo])

    def test_injecao_no_numero_nao_chega_ao_banco(self):
        c = self.cliente_com_plano()
        for ruim in ["5587999990000'; DROP TABLE telefones;--", "5587999990000 OR 1=1", "55879999900\x0000",
                     "me ligue no 5587999990000", "<b>5587999990000</b>"]:
            self.assertEqual(c.req("POST", "/api/telefones", {"numero": ruim}).status, 400, repr(ruim))
        self.assertIn("telefones", sql("SHOW TABLES"))
        self.assertEqual(c.req("GET", "/api/telefones", csrf=False).corpo, [])   # nada foi guardado


class TestA09Admin(Base):
    def admin(self):
        c = Cliente(self.base); c.cadastrar(nome="Admin Teste")
        sql(f"UPDATE usuarios SET papel='admin' WHERE email='{c.email}'")
        return c

    def telefone_pendente(self, plano_id=None):
        dono = self.cliente_com_plano(plano_id)
        n = numero_unico()
        tid = dono.req("POST", "/api/telefones", {"numero": n})["id"]
        return dono, tid, n

    def test_usuario_comum_recebe_403_em_todas_as_rotas(self):
        dono, tid, _ = self.telefone_pendente()
        for metodo, caminho in [("GET", "/api/admin/telefones"), ("GET", "/api/admin/telefones?status=todos"),
                                ("POST", f"/api/admin/telefones/{tid}/aprovar"), ("POST", f"/api/admin/telefones/{tid}/revogar")]:
            r = dono.req(metodo, caminho, {} if metodo == "POST" else None, csrf=(metodo == "POST"))
            self.assertEqual(r.status, 403, caminho)
        self.assertEqual(sql(f"SELECT status FROM telefones WHERE id={tid}"), "pendente")   # o dono não se aprovou

    def test_sem_login_recebe_401(self):
        anon = Cliente(self.base); anon.me()
        self.assertEqual(anon.req("GET", "/api/admin/telefones", csrf=False).status, 401)
        self.assertEqual(anon.req("POST", "/api/admin/telefones/1/aprovar", {}).status, 401)

    def test_post_do_admin_sem_csrf_recebe_403(self):
        adm = self.admin()
        _, tid, _ = self.telefone_pendente()
        self.assertEqual(adm.req("POST", f"/api/admin/telefones/{tid}/aprovar", {}, csrf=False).status, 403)
        self.assertEqual(adm.req("POST", f"/api/admin/telefones/{tid}/aprovar", {}, token="falso").status, 403)
        self.assertEqual(sql(f"SELECT status FROM telefones WHERE id={tid}"), "pendente")

    def test_fila_de_aprovacao_mostra_dono_plano_e_numero(self):
        adm = self.admin()
        dono, tid, n = self.telefone_pendente(plano_unico())
        fila = adm.req("GET", "/api/admin/telefones", csrf=False)
        self.assertEqual(fila.status, 200)
        item = next(t for t in fila.corpo if t["id"] == tid)
        self.assertEqual((item["numero"], item["status"]), (n, "pendente"))
        self.assertEqual((item["usuario"]["email"], item["usuario"]["plano"]), (dono.email, "Único"))
        self.assertIsNone(item["decidido_por"])

    def test_filtro_por_status(self):
        adm = self.admin()
        _, a, _ = self.telefone_pendente(); _, b, _ = self.telefone_pendente(); _, c, _ = self.telefone_pendente()
        adm.req("POST", f"/api/admin/telefones/{b}/aprovar", {}); adm.req("POST", f"/api/admin/telefones/{c}/revogar", {})
        ids = lambda s: {t["id"] for t in adm.req("GET", f"/api/admin/telefones?status={s}", csrf=False).corpo}
        self.assertEqual((a in ids("pendente"), b in ids("pendente"), c in ids("pendente")), (True, False, False))
        self.assertEqual((b in ids("aprovado"), a in ids("aprovado")), (True, False))
        self.assertEqual((c in ids("revogado"), a in ids("revogado")), (True, False))
        self.assertTrue({a, b, c} <= ids("todos"))
        self.assertEqual(adm.req("GET", "/api/admin/telefones?status=qualquer", csrf=False).status, 400)
        self.assertEqual(adm.req("GET", "/api/admin/telefones?status=" + urllib.parse.quote("' OR 1=1 --"), csrf=False).status, 400)

    def test_aprovar_registra_quem_decidiu_e_libera_o_worker(self):
        adm = self.admin()
        dono, tid, n = self.telefone_pendente(plano_unico())
        self.assertNotIn(n, [t["numero"] for t in worker(self.base, "GET", "/api/worker/telefones").corpo])   # pendente não entra
        r = adm.req("POST", f"/api/admin/telefones/{tid}/aprovar", {})
        self.assertEqual((r.status, r["status"]), (200, "aprovado"))
        self.assertEqual(r["decidido_por"]["email"], adm.email)
        self.assertNotEqual(sql(f"SELECT aprovado_por FROM telefones WHERE id={tid}"), "NULL")
        no_worker = {t["numero"]: t["tenants"] for t in worker(self.base, "GET", "/api/worker/telefones").corpo}
        self.assertEqual(no_worker[n], ["pe-estado", "pe-garanhuns"])
        self.assertEqual(dono.req("GET", "/api/telefones", csrf=False).corpo[0]["status"], "aprovado")   # o dono vê o resultado

    def test_revogar_corta_o_acesso(self):
        adm = self.admin()
        _, tid, n = self.telefone_pendente()
        adm.req("POST", f"/api/admin/telefones/{tid}/aprovar", {})
        self.assertIn(n, [t["numero"] for t in worker(self.base, "GET", "/api/worker/telefones").corpo])
        r = adm.req("POST", f"/api/admin/telefones/{tid}/revogar", {})
        self.assertEqual((r.status, r["status"]), (200, "revogado"))
        self.assertNotIn(n, [t["numero"] for t in worker(self.base, "GET", "/api/worker/telefones").corpo])

    def test_recusar_um_pendente_e_reconsiderar_um_revogado(self):
        adm = self.admin()
        _, tid, n = self.telefone_pendente()
        self.assertEqual(adm.req("POST", f"/api/admin/telefones/{tid}/revogar", {})["status"], "revogado")
        self.assertEqual(adm.req("POST", f"/api/admin/telefones/{tid}/aprovar", {})["status"], "aprovado")
        self.assertIn(n, [t["numero"] for t in worker(self.base, "GET", "/api/worker/telefones").corpo])

    def test_repetir_a_decisao_nao_troca_quem_decidiu(self):
        primeiro, segundo = self.admin(), self.admin()
        _, tid, _ = self.telefone_pendente()
        a = primeiro.req("POST", f"/api/admin/telefones/{tid}/aprovar", {})
        b = segundo.req("POST", f"/api/admin/telefones/{tid}/aprovar", {})
        self.assertEqual((a.status, b.status), (200, 200))
        self.assertEqual(b["decidido_por"]["email"], primeiro.email)
        self.assertEqual(a["atualizado_em"], b["atualizado_em"])

    def test_telefone_inexistente_recebe_404(self):
        adm = self.admin()
        self.assertEqual(adm.req("POST", "/api/admin/telefones/999999/aprovar", {}).status, 404)
        self.assertEqual(adm.req("POST", "/api/admin/telefones/999999/revogar", {}).status, 404)

    def test_aprovado_sem_plano_ativo_nao_aparece_para_o_worker(self):
        adm = self.admin()
        dono, tid, n = self.telefone_pendente()
        adm.req("POST", f"/api/admin/telefones/{tid}/aprovar", {})
        sql(f"UPDATE assinaturas a JOIN usuarios u ON u.id=a.usuario_id SET a.status='cancelada' WHERE u.email='{dono.email}'")
        self.assertNotIn(n, [t["numero"] for t in worker(self.base, "GET", "/api/worker/telefones").corpo])

    def test_perder_o_papel_de_admin_corta_o_acesso_na_hora(self):
        adm = self.admin()
        self.assertEqual(adm.req("GET", "/api/admin/telefones", csrf=False).status, 200)
        sql(f"UPDATE usuarios SET papel='usuario' WHERE email='{adm.email}'")
        self.assertEqual(adm.req("GET", "/api/admin/telefones", csrf=False).status, 403)

    def test_papel_nao_pode_ser_alterado_pela_api(self):
        c = Cliente(self.base)
        r = c.req("POST", "/api/cadastro", {"nome": "x", "email": f"{uuid.uuid4().hex[:8]}@teste.local", "senha": "senha-segura-123", "papel": "admin"})
        self.assertEqual(r.status, 201)
        self.assertEqual(r["usuario"]["papel"], "usuario")
        self.assertEqual(c.req("GET", "/api/admin/telefones", csrf=False).status, 403)


class TestPerguntasVencidas(Base):
    """RF-14: falha ou demora gera mensagem legível, e a pergunta não fica presa."""

    def test_fila_parada_vira_erro_legivel(self):
        c = self.cliente_com_plano()
        pid = c.perguntar()["id"]
        sql(f"UPDATE perguntas SET criada_em = NOW(3) - INTERVAL 130 SECOND WHERE id={pid}")
        r = c.req("GET", f"/api/perguntas/{pid}/eventos", csrf=False)
        self.assertEqual(r["status"], "erro")
        self.assertEqual(r["eventos"][-1]["tipo"], "erro")
        self.assertIn("indisponível", r["eventos"][-1]["dados"]["motivo"])
        self.assertEqual(c.perguntar("de novo").status, 201)   # a conta não fica travada

    def test_processando_por_mais_de_180s_vira_erro(self):
        c = self.cliente_com_plano()
        pid = c.perguntar()["id"]
        worker(self.base, "POST", "/api/worker/proxima")
        worker(self.base, "POST", f"/api/worker/perguntas/{pid}/eventos", {"eventos": [{"seq": 1, "tipo": "texto", "dados": {"delta": "parcial"}}]})
        sql(f"UPDATE perguntas SET iniciada_em = NOW(3) - INTERVAL 200 SECOND WHERE id={pid}")
        r = c.req("GET", f"/api/perguntas/{pid}/eventos?desde=1", csrf=False)
        self.assertEqual((r["status"], r["eventos"][0]["seq"], r["eventos"][0]["tipo"]), ("erro", 2, "erro"))
        self.assertIn("demorou", r["eventos"][0]["dados"]["motivo"])
        # o worker que ainda tentava responder é avisado de que a pergunta foi encerrada
        tardio = worker(self.base, "POST", f"/api/worker/perguntas/{pid}/eventos", {"eventos": [{"seq": 3, "tipo": "fim", "dados": {}}]})
        self.assertEqual(tardio.status, 409)

    def test_pergunta_recente_nao_e_tocada(self):
        c = self.cliente_com_plano()
        pid = c.perguntar()["id"]
        self.assertEqual(c.req("GET", f"/api/perguntas/{pid}/eventos", csrf=False)["status"], "fila")


class TestRobustez(Base):
    def test_metodo_errado_e_rota_inexistente(self):
        self.assertEqual(chamar(self.base, "GET", "/api/login").status, 405)
        self.assertEqual(chamar(self.base, "DELETE", "/api/planos").status, 405)
        self.assertEqual(chamar(self.base, "GET", "/api/nao-existe").status, 404)
        self.assertEqual(chamar(self.base, "GET", "/api/registros").status, 404)   # rota do modelo antigo, removida

    def test_arquivos_internos_nao_respondem(self):
        for arq in ["lib_base.php", "lib_conta.php", "lib_chat.php", "lib_worker.php"]:
            r = chamar(self.base, "GET", f"/api/{arq}")
            self.assertEqual(r.status, 404, arq)
            self.assertNotIn("function", json.dumps(r.corpo))

    def test_saude_confere_o_banco(self):
        r = chamar(self.base, "GET", "/api/saude")
        self.assertEqual((r.status, r["ok"]), (200, True))

    def test_resposta_nunca_expoe_hash_nem_chave(self):
        c = self.cliente_com_plano()
        textos = [json.dumps(c.me().corpo), json.dumps(chamar(self.base, "GET", "/api/planos").corpo)]
        for t in textos:
            self.assertNotIn("senha", t)
            self.assertNotIn("$2y$", t)
            self.assertNotIn(WORKER_KEY, t)


if __name__ == "__main__":
    unittest.main(verbosity=1)
