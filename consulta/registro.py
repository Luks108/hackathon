"""Log estruturado do projeto: um arquivo NDJSON por subsistema em logs/, uma linha por evento.

    import registro
    registro.registrar("agente", "tentativa_fim", request_id="wa:3EB0...", modelo="claude-sonnet-5-5", duracao_ms=4210)

Subsistemas (um arquivo cada): gateway, worker, agente, ferramentas, seguranca, saude  ->  logs/<subsistema>.jsonl

Cada linha: ts (local, com milissegundos e fuso), nivel, subsistema, evento, request_id (quando há) e os campos do evento.
O request_id acompanha a pergunta de ponta a ponta: `wa:<id da mensagem>` no WhatsApp, `site:<id da pergunta>` no site.

Regras que este módulo garante, mesmo que quem chama erre:
  - nunca derruba quem chama (qualquer falha de gravação é engolida);
  - nunca grava chave, token, senha, telefone, CPF, e-mail nem o texto de uma mensagem (campos com esses nomes viram "[omitido]";
    textos soltos passam por uma máscara; ver `limpar`);
  - nível configurável por LOG_NIVEL (debug, info, aviso, erro; padrão info);
  - rotação por tamanho: LOG_MAX_MB (padrão 10) e LOG_ARQUIVOS (padrão 5 cópias: x.jsonl.1 ... x.jsonl.5).
Pasta: FORNEXIA_LOGS_DIR, senão logs/ na raiz do projeto. Sob `python -m unittest` sem a variável, vai para uma pasta temporária,
para os testes nunca sujarem o log de verdade.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SUBSISTEMAS = ("gateway", "worker", "agente", "ferramentas", "seguranca", "saude")
NIVEIS = {"debug": 10, "info": 20, "aviso": 30, "erro": 40}
_trava = threading.Lock()

CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TELEFONE = re.compile(r"(?<![\d.])(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}(?![\d.])")
SEGREDO = re.compile(r"(?i)\b(?:sk-[a-z0-9_\-]{12,}|bearer\s+[a-z0-9._\-]{12,}|AIza[0-9A-Za-z_\-]{20,}|eyJ[0-9A-Za-z_\-]{20,})")
# Trechos que, em QUALQUER parte do nome de um campo, impedem o valor de entrar no log ("chave_pf", "access_token", "telefones", "mensagens"...).
# Desenho seguro: o que não se conhece é omitido. Por isso é por trecho (pega o plural e as variações) e não por palavra inteira.
PROIBIDOS_NO_NOME = ("chave", "token", "senha", "password", "secret", "api_key", "apikey", "authorization", "cookie", "telefone", "remetente",
                     "chat_id", "jid", "texto", "mensage", "pergunta", "conteudo", "resposta", "numero_wa")      # "mensage" pega mensagem e mensagens
# Contagens e medidas (nunca o conteúdo) são a ÚNICA exceção: "tamanho_texto", "texto_len", e os três nomes exatos de tokens abaixo.
# (Um prefixo "tokens_" geral deixaria passar "tokens_acesso": por isso a exceção dos tokens de modelo é por nome exato.)
PREFIXOS_DE_MEDIDA = ("tamanho_", "qtd_")
SUFIXOS_DE_MEDIDA = ("_len", "_tamanho", "_bytes", "_ms", "_s")
# Exceção: campos de trecho curto escolhidos de propósito (ex.: o trecho que disparou um alerta de segurança).
PERMITIDOS = ("trecho", "tokens_entrada", "tokens_saida", "tokens_total")
LIMITE_TEXTO = 300


def pasta() -> Path:
    env = os.environ.get("FORNEXIA_LOGS_DIR", "").strip()
    if env:
        return Path(env)
    principal = sys.modules.get("__main__")
    if getattr(getattr(principal, "__spec__", None), "name", "").startswith("unittest"):
        return Path(tempfile.gettempdir()) / "fornexia-logs-teste"
    return RAIZ / "logs"


def nivel_minimo() -> int:
    return NIVEIS.get(os.environ.get("LOG_NIVEL", "info").strip().lower(), NIVEIS["info"])


def _inteiro(nome: str, padrao: int) -> int:
    try:
        return max(int(os.environ.get(nome, padrao)), 1)
    except ValueError:
        return padrao


def novo_request_id(prefixo: str = "cli") -> str:
    return f"{prefixo}:{uuid.uuid4().hex[:12]}"


def mascarar(texto: str) -> str:
    """Troca CPF, e-mail, telefone e segredos conhecidos por marcas. Não é um detector perfeito: é a rede de segurança."""
    texto = SEGREDO.sub("[SEGREDO]", texto)
    texto = EMAIL.sub("[EMAIL]", texto)
    texto = CPF.sub("[CPF]", texto)
    return TELEFONE.sub("[TEL]", texto)


def proibido(chave: str) -> bool:
    """O campo não pode levar o valor original para o log (segredo, telefone ou conteúdo de mensagem)?"""
    nome = chave.lower()
    if nome in PERMITIDOS or nome.startswith(PREFIXOS_DE_MEDIDA) or nome.endswith(SUFIXOS_DE_MEDIDA):
        return False
    return any(p in nome for p in PROIBIDOS_NO_NOME)


def limpar(valor, chave: str = ""):
    if proibido(chave):
        return "[omitido]"
    if isinstance(valor, str):
        return mascarar(valor)[:LIMITE_TEXTO]
    if isinstance(valor, dict):
        return {str(k): limpar(v, str(k)) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [limpar(v, chave) for v in list(valor)[:50]]
    if isinstance(valor, (int, float, bool)) or valor is None:
        return valor
    return limpar(str(valor), chave)


def _rotacionar(caminho: Path, maximo: int, copias: int) -> None:
    try:
        if caminho.stat().st_size < maximo:
            return
    except OSError:
        return
    try:
        for i in range(copias - 1, 0, -1):
            origem = caminho.with_name(f"{caminho.name}.{i}")
            if origem.exists():
                os.replace(origem, caminho.with_name(f"{caminho.name}.{i + 1}"))
        os.replace(caminho, caminho.with_name(f"{caminho.name}.1"))
    except OSError:
        pass        # outro processo pode estar com o arquivo aberto (Windows): tenta de novo na próxima gravação


def registrar(subsistema: str, evento: str, nivel: str = "info", request_id: str | None = None, *, pasta_destino=None, **campos) -> None:
    """Grava uma linha. Nunca levanta. `pasta_destino` troca a pasta (o servidor de ferramentas grava ao lado do consultas.jsonl)."""
    try:
        if subsistema not in SUBSISTEMAS or NIVEIS.get(nivel, 0) < nivel_minimo():
            return
        linha = {"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"), "nivel": nivel,
                 "subsistema": subsistema, "evento": evento}
        if request_id:
            linha["request_id"] = str(request_id)[:80]
        linha.update({k: limpar(v, k) for k, v in campos.items()})
        texto = json.dumps(linha, ensure_ascii=False, default=str) + "\n"
        destino = Path(pasta_destino) if pasta_destino else pasta()
        with _trava:
            destino.mkdir(parents=True, exist_ok=True)
            caminho = destino / f"{subsistema}.jsonl"
            _rotacionar(caminho, _inteiro("LOG_MAX_MB", 10) * 1024 * 1024, _inteiro("LOG_ARQUIVOS", 5))
            with caminho.open("a", encoding="utf-8", newline="") as f:
                f.write(texto)
    except Exception:  # noqa: BLE001  o log jamais pode derrubar o sistema
        pass


def ator(identificador: str) -> str:
    """Apelido estável de quem escreve (por exemplo, um número de WhatsApp), sem poder voltar ao número: HMAC com um sal local
    que fica em logs/ e nunca sai da máquina. Serve para ver "o mesmo remetente tentou 5 ataques" sem gravar o telefone."""
    try:
        arquivo = pasta() / ".sal-ator"
        if not arquivo.exists():
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(secrets.token_hex(16), encoding="utf-8")
            try:
                os.chmod(arquivo, 0o600)
            except OSError:
                pass
        sal = arquivo.read_text(encoding="utf-8").strip().encode()
        # "a" + 9 hexadecimais: um apelido só de dígitos (1% dos casos com 10 hexadecimais) seria trocado por [TEL] pela máscara de telefone.
        return "a" + hmac.new(sal, str(identificador).encode(), hashlib.sha256).hexdigest()[:9]
    except Exception:  # noqa: BLE001
        return "desconhecido"
