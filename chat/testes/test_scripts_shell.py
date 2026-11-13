"""Os scripts `ligar-tudo.sh` e `parar-tudo.sh` (Linux/macOS): sintaxe e LÓGICA, sem Docker, PHP, bun, WhatsApp nem modelo.

Os programas de verdade (docker, php, bun, curl, pgrep e o python do worker) são trocados por "programas de mentira" numa pasta temporária;
os scripts rodam numa CÓPIA temporária do projeto, então os logs e os PIDs reais não são tocados. O que isto prova: a ordem dos passos, que rodar
de novo não duplica nada, o aviso quando o número não está pareado, que um status antigo não engana, a saída quando o Docker está desligado e que
parar só encerra o que o projeto ligou. O que NÃO prova: o comportamento num Linux de verdade (systemd, /proc, setsid, grupo docker).

    python -m unittest discover -s chat/testes -v
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
NT = os.name == "nt"


def achar_bash() -> str | None:
    if NT:      # no Windows, o `bash` do PATH pode ser o do WSL: prefira o Git Bash
        for c in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if Path(c).exists():
                return c
    return shutil.which("bash")


BASH = achar_bash()
SCRIPTS = ["scripts/ligar-tudo.sh", "scripts/parar-tudo.sh", "ligar-tudo.sh", "parar-tudo.sh", "canal-whatsapp/parear.sh"]

# Programas de mentira. Cada processo "de longa duração" se registra em $STUB_DIR/procs ("pid|linha de comando") para o pgrep de mentira achar.
STUBS = {
    "docker": r'''#!/usr/bin/env bash
case "$1" in
  info) [ -f "$STUB_DIR/docker_off" ] && exit 1; exit 0 ;;
  inspect) [ -f "$STUB_DIR/db_doente" ] && echo unhealthy || echo healthy; exit 0 ;;
  compose) echo "compose $*" >> "$STUB_DIR/docker.calls"; exit 0 ;;
esac
exit 0
''',
    # o php de mentira "escuta" enquanto vive (arquivo site_up) e deixa de escutar ao receber SIGTERM, como o de verdade
    "php": '#!/usr/bin/env bash\necho "$$|php $*" >> "$STUB_DIR/procs"\ntouch "$STUB_DIR/site_up"\n'
           'trap \'rm -f "$STUB_DIR/site_up"; kill "$!" 2>/dev/null; exit 0\' TERM\nsleep 600 &\nwait $!\n',
    "bun": r'''#!/usr/bin/env bash
echo "$$|bun $*" >> "$STUB_DIR/procs"
if [ ! -f "$STUB_DIR/bun_mudo" ]; then sleep 1; echo '{"conectado":true,"atualizado":"agora"}' > "$WHATSAPP_STATE_DIR/status.json"; fi
trap 'kill "$!" 2>/dev/null; exit 0' TERM
sleep 600 &
wait $!
''',
    "python3": r'''#!/usr/bin/env bash
echo "$$|python3 $*" >> "$STUB_DIR/procs"
echo "10:00:00 worker no ar: http://127.0.0.1:8080/api com 3 agentes no site"
trap 'kill "$!" 2>/dev/null; exit 0' TERM
sleep 600 &
wait $!
''',
    "pgrep": r'''#!/usr/bin/env bash
[ "$1" = "-f" ] && shift
[ -f "$STUB_DIR/procs" ] || exit 1
achou=1
while IFS='|' read -r pid cmd; do
  kill -0 "$pid" 2>/dev/null || continue
  if printf '%s' "$cmd" | grep -Eq "$1"; then echo "$pid"; achou=0; fi
done < "$STUB_DIR/procs"
exit $achou
''',
}


# O `curl` de mentira é uma FUNÇÃO carregada por BASH_ENV: ela vence qualquer curl do PATH (no Git Bash do Windows o /mingw64/bin/curl passa na frente
# de uma pasta de stubs e acabaria batendo no site real da porta 8080).
BASH_ENV_CURL = 'curl() { [ -f "$STUB_DIR/site_up" ]; }\n'


@unittest.skipUnless(BASH, "precisa do bash")
class TestSintaxe(unittest.TestCase):
    def test_todos_os_scripts_de_shell_passam_no_bash_n(self):
        for s in SCRIPTS:
            r = subprocess.run([BASH, "-n", str(RAIZ / s)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{s}: {r.stderr}")

    def test_scripts_usam_fim_de_linha_unix(self):
        for s in SCRIPTS:
            self.assertNotIn(b"\r\n", (RAIZ / s).read_bytes(), f"{s} com CRLF quebra no Linux (o .gitattributes manda LF)")


@unittest.skipUnless(BASH, "precisa do bash")
class TestLogica(unittest.TestCase):
    PGREP_REAL = False      # True: usa o pgrep (e o /proc) do sistema em vez do pgrep de mentira

    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="ligar-teste-"))
        self.repo, self.stub, self.estado = self.t / "repo", self.t / "stub", self.t / "estado"
        for d in (self.repo / "scripts", self.repo / "canal-whatsapp", self.stub / "bin", self.estado / "auth"):
            d.mkdir(parents=True)
        for s in ("ligar-tudo.sh", "parar-tudo.sh"):
            shutil.copy(RAIZ / "scripts" / s, self.repo / "scripts" / s)
        for nome, corpo in STUBS.items():
            if nome == "pgrep" and self.PGREP_REAL:
                continue
            (self.stub / "bin" / nome).write_text(corpo, encoding="utf-8", newline="\n")
            os.chmod(self.stub / "bin" / nome, 0o755)      # no Linux, sem isto o `command -v` ignora o stub e acha o programa de verdade
        (self.stub / "bashenv.sh").write_text(BASH_ENV_CURL, encoding="utf-8", newline="\n")
        (self.estado / "auth" / "creds.json").write_text('{"registered":true}', encoding="utf-8")
        # status ANTIGO dizendo "conectado": o script não pode se enganar com ele
        antigo = self.estado / "status.json"
        antigo.write_text('{"conectado":true,"atualizado":"ontem"}', encoding="utf-8")
        os.utime(antigo, (time.time() - 3600, time.time() - 3600))
        sep = ";" if NT else ":"
        self.env = {**os.environ, "STUB_DIR": self.stub.as_posix(), "WHATSAPP_STATE_DIR": self.estado.as_posix(), "LIGAR_TEMPO_MAX": "8",
                    "PATH": f"{(self.stub / 'bin').as_posix()}{sep}{os.environ['PATH']}", "HOME": self.t.as_posix(),
                    "BASH_ENV": (self.stub / "bashenv.sh").as_posix()}

    def tearDown(self):
        procs = self.stub / "procs"
        if procs.exists():
            for linha in procs.read_text().splitlines():
                pid = linha.split("|")[0]
                # TERM primeiro: o php de mentira tem um trap que mata o `sleep` filho; só depois KILL
                subprocess.run([BASH, "-c", f"kill -TERM {pid} 2>/dev/null; sleep 0.3; kill -KILL {pid} 2>/dev/null"], capture_output=True)
        shutil.rmtree(self.t, ignore_errors=True)

    def rodar(self, script: str, *args: str, limite=90) -> subprocess.CompletedProcess:
        return subprocess.run([BASH, str(self.repo / "scripts" / script), *args], capture_output=True, text=True, encoding="utf-8",
                              env=self.env, timeout=limite)

    def vivos(self, nome: str) -> int:
        procs = self.stub / "procs"
        if not procs.exists():
            return 0
        n = 0
        for linha in procs.read_text().splitlines():
            pid, _, cmd = linha.partition("|")
            if cmd.startswith(nome) and subprocess.run([BASH, "-c", f"kill -0 {pid} 2>/dev/null"]).returncode == 0:
                n += 1
        return n

    def pids(self) -> int:
        return sum(self.vivos(n) for n in ("php", "bun", "python3"))

    # ---- ligar ----
    def test_liga_tudo_do_zero_na_ordem_e_sobe_uma_de_cada(self):
        r = self.rodar("ligar-tudo.sh")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        posicoes = [r.stdout.index(x) for x in ("1/5  Docker", "2/5  Bancos", "3/5  Site", "4/5  Gateway", "5/5  Worker")]
        self.assertEqual(posicoes, sorted(posicoes))
        for esperado in ("hackathon-site-db saudável", "no ar (http://127.0.0.1:8080)", "conectado ao WhatsApp", "Worker rodando"):
            self.assertIn(esperado, r.stdout)
        self.assertEqual((self.vivos("php"), self.vivos("bun"), self.vivos("python3")), (1, 1, 2))      # python3 = worker + vigia
        chamadas = (self.stub / "docker.calls").read_text()
        self.assertIn("site/dev/docker-compose.yml up -d", chamadas)
        self.assertIn("infra/docker-compose.yml up -d neo4j", chamadas)
        for nome in ("site", "gateway", "worker", "vigia"):
            self.assertTrue((self.repo / "logs" / "run" / f"{nome}.pid").exists(), nome)
        self.assertIn("worker no ar", (self.repo / "logs" / "worker.log").read_text())
        self.assertIn("vigia de saúde no ar", r.stdout)
        self.assertIn("chat/vigia.py", (self.stub / "procs").read_text())          # o vigia subiu com o python do projeto

    def test_rodar_de_novo_nao_duplica_nada(self):
        self.rodar("ligar-tudo.sh")
        antes = self.pids()
        r = self.rodar("ligar-tudo.sh")
        self.assertEqual(self.pids(), antes)
        self.assertEqual(r.stdout.count("já estava"), 3)           # site, gateway e worker
        self.assertIn("vigia de saúde já rodando", r.stdout)
        self.assertEqual((self.vivos("php"), self.vivos("bun"), self.vivos("python3")), (1, 1, 2))      # python3 = worker + vigia

    def test_status_so_mostra_e_nao_sobe_nada(self):
        r = self.rodar("ligar-tudo.sh", "--status")
        self.assertEqual(self.pids(), 0)
        self.assertIn("Site local fora do ar", r.stdout)
        self.assertIn("Worker parado", r.stdout)
        self.assertIn("Vigia de saúde parado", r.stdout)
        self.rodar("ligar-tudo.sh")
        self.assertIn("Vigia de saúde rodando", self.rodar("ligar-tudo.sh", "--status").stdout)
        self.assertIn("Gateway do WhatsApp conectado", self.rodar("ligar-tudo.sh", "--status").stdout)

    def test_sem_pareamento_avisa_nao_sobe_o_gateway_e_sobe_o_worker(self):
        (self.estado / "auth" / "creds.json").write_text('{"registered":false}', encoding="utf-8")
        r = self.rodar("ligar-tudo.sh")
        self.assertIn("ainda não foi pareado", r.stdout)
        self.assertIn("parear.sh", r.stdout)
        self.assertEqual((self.vivos("bun"), self.vivos("python3")), (0, 2))

    def test_status_antigo_conectado_nao_engana_quando_o_gateway_nao_conecta(self):
        (self.stub / "bun_mudo").write_text("")                     # o bun de mentira sobe, mas nunca escreve um status novo
        r = self.rodar("ligar-tudo.sh")
        self.assertIn("ainda sem conexão", r.stdout)
        self.assertNotIn("conectado ao WhatsApp", r.stdout.split("PRONTO")[0].split("4/5")[1].split("5/5")[0])

    def test_docker_desligado_para_na_hora_com_codigo_1_e_nao_sobe_nada(self):
        (self.stub / "docker_off").write_text("")
        r = self.rodar("ligar-tudo.sh")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Docker não está respondendo", r.stdout)
        self.assertIn("systemctl start docker", r.stdout)
        self.assertEqual(self.pids(), 0)

    def test_banco_que_nao_fica_saudavel_para_com_erro_e_nao_sobe_o_resto(self):
        (self.stub / "db_doente").write_text("")
        r = self.rodar("ligar-tudo.sh")
        self.assertEqual(r.returncode, 1)
        self.assertIn("não ficou saudável", r.stdout)
        self.assertEqual(self.pids(), 0)

    # ---- parar ----
    def test_parar_simular_lista_e_nao_mata(self):
        self.rodar("ligar-tudo.sh")
        r = self.rodar("parar-tudo.sh", "--simular")
        self.assertEqual(r.stdout.count("[simulação]"), 4)       # gateway, worker, vigia e site
        self.assertEqual((self.vivos("php"), self.vivos("bun"), self.vivos("python3")), (1, 1, 2))      # python3 = worker + vigia

    def test_parar_encerra_os_quatro_limpa_os_pids_e_rodar_de_novo_diz_que_nao_ha_nada(self):
        self.rodar("ligar-tudo.sh")
        r = self.rodar("parar-tudo.sh")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("encerrado PID"), 4)
        time.sleep(0.5)
        self.assertEqual(self.pids(), 0)
        self.assertEqual(list((self.repo / "logs" / "run").glob("*.pid")), [])
        self.assertIn("Nada do projeto estava rodando", self.rodar("parar-tudo.sh").stdout)

    def test_parar_nao_desliga_o_docker_e_so_com_a_opcao_desliga_os_bancos(self):
        self.rodar("ligar-tudo.sh")
        self.rodar("parar-tudo.sh")
        self.assertNotIn(" stop", (self.stub / "docker.calls").read_text())
        self.rodar("parar-tudo.sh", "--com-bancos")
        chamadas = (self.stub / "docker.calls").read_text()
        self.assertIn("docker-compose.yml stop", chamadas)
        self.assertIn("neo4j", chamadas.split("docker-compose.yml stop")[-1])

    def test_parar_recusa_opcao_desconhecida(self):
        r = self.rodar("parar-tudo.sh", "--tudo")
        self.assertEqual(r.returncode, 2)

    def test_ligar_depois_de_parar_sobe_de_novo(self):
        self.rodar("ligar-tudo.sh")
        self.rodar("parar-tudo.sh")
        time.sleep(0.5)
        (self.estado / "status.json").write_text('{"conectado":false,"parado":true}', encoding="utf-8")
        r = self.rodar("ligar-tudo.sh")
        self.assertIn("conectado ao WhatsApp", r.stdout)
        self.assertEqual((self.vivos("php"), self.vivos("bun"), self.vivos("python3")), (1, 1, 2))      # python3 = worker + vigia


@unittest.skipUnless(BASH and not NT and shutil.which("pgrep") and Path("/proc/self/cwd").exists(), "precisa de pgrep e /proc de verdade (Linux)")
class TestLogicaComPgrepReal(TestLogica):
    """Os mesmos testes, mas com o pgrep real e o filtro por /proc/<pid>/cwd do script em ação (só roda no Linux, por exemplo no WSL)."""
    PGREP_REAL = True


if __name__ == "__main__":
    unittest.main()
