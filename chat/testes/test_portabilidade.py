"""Garante que o agente acha o Python da .venv e o `claude` no Windows e no Linux.

    python -m unittest discover -s chat/testes -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agente  # noqa: E402


class TestCaminhos(unittest.TestCase):
    def test_variavel_de_ambiente_manda(self):
        with mock.patch.dict(os.environ, {"AGENTE_PYTHON": "/x/python", "CLAUDE_BIN": "/x/claude"}):
            self.assertEqual(agente.python_do_projeto(), "/x/python")
            self.assertEqual(agente.achar_claude(), "/x/claude")

    def test_acha_a_venv_nos_dois_formatos(self):
        for relativo in (("Scripts", "python.exe"), ("bin", "python")):
            with tempfile.TemporaryDirectory() as pasta, mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("AGENTE_PYTHON", None)
                alvo = Path(pasta) / ".venv" / Path(*relativo)
                alvo.parent.mkdir(parents=True)
                alvo.write_text("")
                with mock.patch.object(agente, "RAIZ", Path(pasta)):
                    self.assertEqual(agente.python_do_projeto(), str(alvo))

    def test_sem_venv_usa_o_python_atual(self):
        with tempfile.TemporaryDirectory() as pasta, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTE_PYTHON", None)
            with mock.patch.object(agente, "RAIZ", Path(pasta)):
                self.assertEqual(agente.python_do_projeto(), sys.executable)

    def test_claude_no_path_tem_prioridade(self):
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch("shutil.which", return_value="/usr/bin/claude"):
            os.environ.pop("CLAUDE_BIN", None)
            self.assertEqual(agente.achar_claude(), "/usr/bin/claude")


if __name__ == "__main__":
    unittest.main()
