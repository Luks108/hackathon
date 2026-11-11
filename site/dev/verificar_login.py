"""Cria os usuários de teste do site local e confere login, senha e permissões de verdade, pela API.

    python site/dev/verificar_login.py                      # site em http://127.0.0.1:8080
    python site/dev/verificar_login.py http://127.0.0.1:8080

Contas de teste (só para desenvolvimento local; a senha NÃO serve em nenhum outro lugar):
    admin@local.test     senha-local-123      administrador (criado por: php site/setup.php admin@local.test "Admin Local" senha-local-123)
    usuario@local.test   usuario-local-123    conta comum (este script cria na primeira vez)

Confere: senha errada recusada, e-mail inexistente recusado, senha certa entra, conta comum NÃO acessa a administração,
administrador acessa, sem login a API recusa, a área técnica exige login. Sai com 0 se tudo passou, 1 se algo falhou.
"""
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8080").rstrip("/")
ADMIN = ("admin@local.test", "senha-local-123")
USUARIO = ("usuario@local.test", "usuario-local-123")


class Cliente:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ""
        self.chamar("GET", "/me")

    def chamar(self, metodo: str, caminho: str, corpo: dict | None = None):
        req = urllib.request.Request(BASE + "/api" + caminho, method=metodo, data=json.dumps(corpo).encode() if corpo is not None else None,
                                     headers={"Content-Type": "application/json", "X-CSRF-Token": self.csrf})
        try:
            with self.opener.open(req, timeout=20) as r:
                status, texto = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, texto = e.code, e.read()
        try:
            dados = json.loads(texto or b"{}")
        except ValueError:
            dados = {}
        self.csrf = dados.get("csrf", self.csrf) if isinstance(dados, dict) else self.csrf
        return status, dados


falhas = 0


def confere(descricao: str, ok: bool, detalhe: str = ""):
    global falhas
    falhas += not ok
    print(("OK     " if ok else "FALHOU ") + descricao + ("" if ok else f"  <- {detalhe}"))


def main() -> int:
    try:
        urllib.request.urlopen(BASE + "/api/saude", timeout=5).read()
    except OSError:
        print(f"O site não respondeu em {BASE}. Suba com: php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php")
        return 1

    # Conta comum: cria na primeira vez (409 = já existe).
    status, _ = Cliente().chamar("POST", "/cadastro", {"nome": "Usuário de Teste", "email": USUARIO[0], "senha": USUARIO[1]})
    print({201: "conta comum criada", 409: "conta comum já existia"}.get(status, f"cadastro respondeu {status}"))
    print()

    c = Cliente()
    s, _ = c.chamar("POST", "/login", {"email": USUARIO[0], "senha": "senha-errada-999"})
    confere("senha errada é recusada (401)", s == 401, f"HTTP {s}")
    s, _ = c.chamar("POST", "/login", {"email": "ninguem@local.test", "senha": "qualquer-coisa-1"})
    confere("e-mail inexistente é recusado (401), com a mesma resposta", s == 401, f"HTTP {s}")

    s, d = Cliente().chamar("GET", "/painel")
    confere("sem login, a área técnica é recusada (401)", s == 401, f"HTTP {s}")
    s, d = Cliente().chamar("GET", "/admin/telefones")
    confere("sem login, a administração é recusada (401)", s == 401, f"HTTP {s}")

    u = Cliente()
    s, d = u.chamar("POST", "/login", {"email": USUARIO[0], "senha": USUARIO[1]})
    confere("conta comum entra com a senha certa (200)", s == 200 and d.get("usuario", {}).get("papel") == "usuario", f"HTTP {s} {d}")
    if not d.get("plano"):   # a tela do site faz isto sozinha logo depois do login (Api.garantirPlano)
        planos = u.chamar("GET", "/planos")[1]
        if isinstance(planos, list) and planos:
            padrao = sorted(planos, key=lambda p: (-len(p["tenants"]), -p["preco_mensal"]))[0]
            s, d2 = u.chamar("POST", "/assinatura", {"plano_id": padrao["id"]})
            d = {**d, "plano": d2.get("plano")} if s in (200, 201) else d
    confere("conta comum recebe o plano único ao entrar (como a tela faz)", bool(d.get("plano")), "sem plano: o chat não deixaria perguntar")
    s, d = u.chamar("GET", "/admin/telefones")
    confere("conta comum NÃO acessa a administração (403)", s == 403, f"HTTP {s}")
    s, d = u.chamar("GET", "/painel")
    confere("conta comum acessa a área técnica (200; 503 = painel.json ainda não gerado)", s in (200, 503), f"HTTP {s}")
    if s == 503:
        print("       -> gere o painel de teste: python consulta/gerar_painel.py --dev")
    s, _ = u.chamar("POST", "/logout")
    s2, _ = u.chamar("GET", "/painel")
    confere("depois de sair, a área técnica volta a ser recusada (401)", s2 == 401, f"HTTP {s2}")

    a = Cliente()
    s, d = a.chamar("POST", "/login", {"email": ADMIN[0], "senha": ADMIN[1]})
    if s != 200:
        confere("administrador entra", False, f"HTTP {s}: rode  php site/setup.php admin@local.test \"Admin Local\" senha-local-123")
    else:
        confere("administrador entra (200) com papel admin", d.get("usuario", {}).get("papel") == "admin", str(d))
        s, d = a.chamar("GET", "/admin/telefones")
        confere("administrador acessa a administração (200)", s == 200, f"HTTP {s}")

    print("\nTudo certo." if not falhas else f"\n{falhas} verificação(ões) falharam.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
