"""Teste de fumaça do site em um navegador de verdade (sem janela).

    python site/dev/fumaca_navegador.py                       # site em http://127.0.0.1:8080
    python site/dev/fumaca_navegador.py http://127.0.0.1:8080
    NAVEGADOR="C:/caminho/chrome.exe" python site/dev/fumaca_navegador.py

Abre cada página num Chrome, Edge ou Chromium escondido, espera o JavaScript rodar e confere que a tela certa apareceu.
Isso prova que HTML, CSS, JavaScript e a API estão conversando. Não faz login nem pergunta nada ao agente.

Não funciona no Opera: o teste precisa do modo de depuração do Chromium (`--dump-dom`), que o Opera não oferece.
Use Chrome, Edge ou Chromium. Sai com código 0 se tudo passou e 1 se algo falhou.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")


def achar_navegador() -> str | None:
    if os.environ.get("NAVEGADOR"):
        return os.environ["NAVEGADOR"]
    candidatos = []
    if os.name == "nt":
        for pasta in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if pasta:
                candidatos += [Path(pasta) / "Microsoft/Edge/Application/msedge.exe",
                               Path(pasta) / "Google/Chrome/Application/chrome.exe"]
    else:
        candidatos += [Path(p) for p in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
                                         "/snap/bin/chromium", "/usr/bin/microsoft-edge")]
    for c in candidatos:
        if c.is_file():
            return str(c)
    for nome in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "chrome", "msedge"):
        achado = shutil.which(nome)
        if achado:
            return achado
    return None


def renderizar(navegador: str, url: str) -> str:
    with tempfile.TemporaryDirectory() as perfil:
        r = subprocess.run(
            [navegador, "--headless", "--disable-gpu", "--no-first-run", "--no-sandbox", f"--user-data-dir={perfil}",
             "--virtual-time-budget=6000", "--dump-dom", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    return r.stdout


def tem_plano_na_pagina(dom: str) -> bool:
    return len(re.findall(r'class="plano-card"', dom)) >= 1


def mostra_tela_de_entrada(dom: str) -> bool:
    entrar = re.search(r'<section id="tela-entrar"[^>]*>', dom)
    carregando = re.search(r'<section id="tela-carregando"[^>]*>', dom)
    return bool(entrar) and "hidden" not in entrar.group(0) and bool(carregando) and "hidden" in carregando.group(0)


# (página, o que conferir, o que significa se falhar)
PAGINAS = [
    ("/", lambda d: "FornexIA" in d and tem_plano_na_pagina(d),
     "a página inicial não mostrou os planos: o JavaScript não rodou ou /api/planos não respondeu"),
    ("/chat.html", mostra_tela_de_entrada,
     "o chat não mostrou a tela de entrar: ficou em 'Carregando…' ou o JavaScript quebrou"),
    ("/conta.html", mostra_tela_de_entrada,
     "sem login, /conta.html deveria mandar para a tela de entrar do chat"),
    ("/admin.html", mostra_tela_de_entrada,
     "sem login, /admin.html deveria mandar para a tela de entrar do chat"),
]


def main() -> int:
    navegador = achar_navegador()
    if not navegador:
        print("Não achei Chrome, Edge nem Chromium. Instale um deles ou defina NAVEGADOR com o caminho do executável.")
        return 1
    print("navegador:", navegador)
    if "opera" in navegador.lower():
        print("O Opera não serve para este teste (falta o modo de depuração). Use Chrome, Edge ou Chromium.")
        return 1
    falhas = 0
    for caminho, confere, significado in PAGINAS:
        try:
            dom = renderizar(navegador, BASE + caminho)
        except subprocess.TimeoutExpired:
            dom = ""
        ok = bool(dom) and confere(dom)
        print(("OK     " if ok else "FALHOU ") + caminho + ("" if ok else "  <- " + (significado if dom else "o navegador não abriu a página (o site está no ar?)")))
        falhas += 0 if ok else 1
    print("\nTudo certo." if not falhas else f"\n{falhas} página(s) com problema.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
