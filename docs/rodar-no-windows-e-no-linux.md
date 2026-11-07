# Rodar o projeto no Windows e no Linux

O mesmo código roda nos dois. Só mudam o caminho do Python da `.venv` e a forma de ativá-la. O código procura sozinho o Python
(`.venv/Scripts/python.exe` no Windows, `.venv/bin/python` no Linux) e o `claude` (no PATH; no Windows, também na extensão do VS Code).

## Preparação (uma vez)

| Passo | Linux | Windows (PowerShell) |
|---|---|---|
| Criar a venv | `python3 -m venv .venv` | `python -m venv .venv` |
| Instalar | `.venv/bin/pip install -r requirements.txt` | `.venv\Scripts\pip install -r requirements.txt` |
| Ativar (opcional) | `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| `.env` | `cp .env.exemplo .env` | `Copy-Item .env.exemplo .env` |
| PHP 8.2 | `apt install php8.2-cli php8.2-mysql` | `winget install PHP.PHP.NTS.8.2` |
| Docker | Docker Engine | Docker Desktop (precisa estar aberto) |
| `bun` (só WhatsApp) | `curl -fsSL https://bun.sh/install \| bash` | `npm install -g bun` |
| `claude` | `npm install -g @anthropic-ai/claude-code` e `claude` para entrar | já vem na extensão do VS Code; ou o mesmo `npm` |

Depois: `cd canal-whatsapp && bun install` (só para o WhatsApp).

Nos exemplos abaixo, `python` é o da `.venv` (ativada, ou o caminho completo).

## Variáveis do `.env`

| Variável | Para quê | Padrão |
|---|---|---|
| `NEO4J_SENHA`, `NEO4J_URI`, `CHAVE_PF`, `BRUTO` | Grafo e dados (veja `.env.exemplo`). `BRUTO` relativo vale a partir da raiz do projeto | |
| `API_BASE` | Site que o worker atende. Local: `http://127.0.0.1:8080`. Sem ela, usa `https://$SITE/api` | `https://hackathon.figueiredo.dev` |
| `WORKER_KEY` | Chave do worker. Tem de ser igual à de `site/hackathon-config.php` do site | obrigatória |
| `AGENTE_MODELO` | Modelo de cada pergunta | `claude-opus-5-5` |
| `AGENTES_SITE` | Perguntas do site atendidas ao mesmo tempo | `3` |
| `AGENTE_PYTHON`, `CLAUDE_BIN` | Só se a detecção automática não achar | |
| `WHATSAPP_STATE_DIR` | Pasta de estado do gateway | `~/.claude/channels/whatsapp-hackathon` |

## Site local + worker real

```bash
docker compose -f site/dev/docker-compose.yml up -d        # banco do site
php site/setup.php admin@local.test "Admin Local" senha-local-123
php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php
docker compose --env-file .env -f infra/docker-compose.yml up -d neo4j
python coleta/carregar_neo4j.py --zerar --exemplo           # dados fictícios

python chat/worker.py                                       # em outro terminal
```

Abra `http://127.0.0.1:8080/chat.html`, crie uma conta e pergunte. Para ver o agente sem o site:

```bash
python chat/agente.py estado "Quais contratos temos na base?"
python chat/worker.py --simular "Existe alguma sanção?"     # como se fosse WhatsApp, sem enviar nada
```

Para testar o site **sem gastar modelo**, use o worker falso em vez do real: `python site/dev/worker_falso.py`.
Nunca deixe os dois rodando juntos para o mesmo site.

## WhatsApp

```bash
cd canal-whatsapp
WA_PAIR_PHONE=5587999999999 bun gateway.ts     # PowerShell: $env:WA_PAIR_PHONE='5587999999999'; bun gateway.ts
bun acesso.ts add 5587999999999                # o primeiro número é o dono
bun acesso.ts status
```

Com o gateway ligado, rode `python chat/worker.py` e mande a mensagem do número liberado. Um número só pode estar ligado a **um**
gateway por vez: não pareie o número que o notebook da exibição usa.

No Linux, para deixar o gateway e o worker como serviço, use `canal-whatsapp/wa-gateway.service` e `chat/chat-worker.service`
(ajuste os caminhos `WorkingDirectory` e `ExecStart`, que apontam para a máquina do Lucas).

## Testes

```bash
python -m unittest discover -s consulta/testes        # 48, precisam do Neo4j com os dados fictícios
python -m unittest discover -s chat/testes            # 4, caminhos e portabilidade
python site/dev/test_api.py                           # 78, precisam do banco; no Windows defina PHP_BIN com o caminho do php.exe
```

## Cuidados de portabilidade

- `*.sh` e `*.service` são sempre gravados com fim de linha LF (`.gitattributes`). Um `deploy.sh` com CRLF não roda no Linux.
- Não escreva caminhos `.venv/bin/...` no código. Use `agente.PYTHON` e `agente.CLAUDE`.
- Para trocar um arquivo de forma atômica, use `os.replace`: `Path.rename` falha no Windows se o destino já existe.
- Arquivo temporário que outro processo vai abrir não pode usar `NamedTemporaryFile` com `delete=True`: no Windows ele fica trancado.
