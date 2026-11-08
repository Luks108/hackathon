# Rodar o projeto no Windows e no Linux

Guia passo a passo para subir o FornexIA ("Histórico de fornecedor com prova") num computador que nunca viu o projeto.
Funciona no **Windows 10/11** (máquina de desenvolvimento) e no **Linux** (máquina da exibição ao cliente).
Siga na ordem. No fim de cada etapa há uma **Conferência**: rode o comando, compare com a saída esperada e só então siga.

> **Pendência:** a conexão do WhatsApp está sendo resolvida por fora. Ela aparece no guia (etapa 11), marcada como **pendente**,
> e **não bloqueia** o resto: o site, o chat e o agente funcionam sem ela.

## Sumário

1. [O que é cada peça](#1-o-que-é-cada-peça)
2. [Antes de começar: equipamento e programas](#2-antes-de-começar-equipamento-e-programas)
3. [Baixar o projeto](#3-baixar-o-projeto)
4. [Python e pacotes](#4-python-e-pacotes)
5. [Configurar o `.env` e a chave do worker](#5-configurar-o-env-e-a-chave-do-worker)
6. [Subir os bancos de dados](#6-subir-os-bancos-de-dados)
7. [Carregar os dados fictícios](#7-carregar-os-dados-fictícios)
8. [Subir o site](#8-subir-o-site)
9. [Subir o worker e conversar com o agente](#9-subir-o-worker-e-conversar-com-o-agente)
10. [Teste de fumaça no navegador](#10-teste-de-fumaça-no-navegador)
11. [WhatsApp (pendente)](#11-whatsapp-pendente)
12. [Testes automáticos](#12-testes-automáticos)
13. [Linux: deixar tudo como serviço](#13-linux-deixar-tudo-como-serviço)
14. [Ordem de subida e sinais de que está no ar](#14-ordem-de-subida-e-sinais-de-que-está-no-ar)
15. [Problemas comuns](#15-problemas-comuns)
16. [Cuidados de portabilidade](#16-cuidados-de-portabilidade)

Em cada bloco de comandos o guia diz **em que sistema** e **em que pasta** rodar. Quando nada é dito, a pasta é a **raiz do
projeto** (a que contém `README.md`). Copie **um comando por vez**.

---

## 1. O que é cada peça

```text
Navegador ──> Site (PHP + MariaDB) <── Worker (Python) ──> Agente (claude -p) ──> consultas ──> Neo4j
                                          └── (WhatsApp, pendente) ◄── Gateway (bun)
```

| Peça | O que faz | Onde roda no guia |
|---|---|---|
| Site | Páginas, contas, planos e a fila de perguntas | `http://127.0.0.1:8080` |
| MariaDB | Banco do site (contas, perguntas) | Docker, porta `3307` |
| Neo4j | Grafo com os fornecedores, contratos e provas | Docker, porta `7689` |
| Worker | Pega a pergunta na fila do site, chama o agente e devolve a resposta | `chat/worker.py` |
| Agente | O modelo (via `claude`), limitado às consultas do projeto | `chat/agente.py` |
| Gateway do WhatsApp | Liga o WhatsApp ao worker | `canal-whatsapp/` (**pendente**) |

**Dois jeitos de usar:**

- **Tudo local (desenvolvimento):** as etapas 3 a 10, no mesmo computador. É o que este guia detalha.
- **Exibição ao cliente:** o site fica publicado na hospedagem (o Lucas cuida do deploy) e o notebook Linux roda só o Neo4j, o
  worker e o gateway. O worker só faz conexões de saída. Nesse caso o `.env` do notebook **não** leva `API_BASE` (ele aponta
  sozinho para o site publicado) e a `WORKER_KEY` é a do site publicado, que o Lucas passa por canal privado.

---

## 2. Antes de começar: equipamento e programas

### Equipamento

| Item | Mínimo | Recomendado |
|---|---|---|
| Memória (RAM) | 8 GB | 16 GB (Docker, Neo4j e o navegador abertos ao mesmo tempo) |
| Disco livre | 10 GB | 20 GB (imagens do Docker e pacotes) |
| Processador | 64 bits, 4 núcleos | 8 núcleos |
| Internet | Obrigatória | O agente usa o modelo pela internet |
| Windows | Windows 10 ou 11, 64 bits, com virtualização ligada na BIOS (o Docker Desktop precisa) | |
| Linux | Ubuntu 22.04/24.04 ou Debian 12, 64 bits | |

Os números de RAM e disco são uma estimativa de bom senso, não uma medição.

### Contas

| Conta | Para quê |
|---|---|
| GitHub com acesso ao repositório `Luks108/hackathon` | Baixar o código |
| Conta do Claude (Claude Code) | O agente roda o modelo com a sua conta. **Cada pergunta consome do seu plano** |

### Programas e versões

| Programa | Versão | Para quê | Como conferir |
|---|---|---|---|
| Git | qualquer recente | Baixar o projeto | `git --version` |
| Python | **3.10 ou mais novo** (o pacote `mcp 2.3.0` exige 3.10+; testado com **3.14.0** no Windows) | Worker, agente, consultas, testes | `python --version` |
| PHP | **8.2** (a mesma versão da hospedagem; só ela foi testada) | Site | `php -v` |
| Docker | Docker Desktop (Windows) ou Docker Engine com o plugin Compose (Linux) | MariaDB 10.11 e Neo4j 5.26 | `docker --version` e `docker compose version` |
| Node.js | **22 ou mais novo** (exigido pelo pacote do Claude Code) | Instalar o `claude` | `node --version` |
| Claude Code (`claude`) | recente | O agente | `claude --version` |
| Bun | 1.4 ou mais novo | **Só para o WhatsApp (pendente)** | `bun --version` |

O projeto não tem `pyproject.toml` nem `package.json` na raiz. As versões acima vêm de `requirements.txt` (`mcp==2.3.0`,
`neo4j==5.28.3`), de `canal-whatsapp/package.json` e das imagens em `infra/` e `site/dev/`.

### Instalar no Windows (PowerShell)

Abra o **PowerShell** (menu Iniciar → "PowerShell"). Não precisa ser administrador, exceto para o Docker Desktop.

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id PHP.PHP.NTS.8.2 -e
winget install --id OpenJS.NodeJS -e
winget install --id Docker.DockerDesktop -e
```

**Feche o PowerShell e abra outro.** O Windows só enxerga programas recém-instalados em terminais abertos *depois* da instalação.

> **Atenção com o Python:** digitar `python` num Windows onde ele não foi instalado **abre a Microsoft Store** em vez de dar erro.
> Se isso acontecer, **não instale pela Store**: feche a Loja e rode o `winget` acima. Se a Loja continuar abrindo mesmo com o
> Python instalado, desligue o atalho: *Configurações → Aplicativos → Configurações avançadas de aplicativos → Aliases de
> execução de aplicativo → desmarque "python.exe" e "python3.exe"*. Na instalação manual (python.org), marque **"Add python.exe
> to PATH"**.

Habilite as extensões do PHP (o PHP do `winget` vem sem `php.ini`). Rode estes comandos, um de cada vez:

```powershell
cd (Split-Path (Get-Command php).Source)
Copy-Item php.ini-development php.ini
(Get-Content php.ini) -replace '^;extension_dir = "ext"','extension_dir = "ext"' -replace '^;extension=(curl|fileinfo|mbstring|mysqli|openssl|pdo_mysql)$','extension=$1' | Set-Content php.ini
php -m | Select-String "pdo_mysql|curl|mbstring|openssl|fileinfo|mysqli"
```

Instale o Claude Code e entre na conta:

```powershell
npm.cmd install -g @anthropic-ai/claude-code
claude --version
claude
```

O último comando abre o login. Entre com a sua conta, depois digite `/exit`. (Use `npm.cmd`, e não `npm`: veja o problema
"npm.ps1 não pode ser carregado" na etapa 15. Se o VS Code com a extensão do Claude Code já está instalado, o projeto acha o
`claude` dela sozinho, mas ele ainda precisa estar com a conta ligada.)

Abra o **Docker Desktop** uma vez e espere o ícone ficar verde ("Engine running"). Ele precisa estar aberto sempre que for usar o
projeto.

### Instalar no Linux (Ubuntu ou Debian, bash)

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip curl unzip
```

O pacote **`python3-venv` é obrigatório** em Ubuntu/Debian limpos: sem ele, `python3 -m venv` falha.

PHP 8.2 (escolha a linha do seu sistema):

```bash
# Debian 12: já traz o 8.2
sudo apt install -y php8.2-cli php8.2-mysql php8.2-curl php8.2-mbstring
```

```bash
# Ubuntu: a versão padrão não é a 8.2. Use o repositório oficial de pacotes PHP
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:ondrej/php
sudo apt update
sudo apt install -y php8.2-cli php8.2-mysql php8.2-curl php8.2-mbstring
```

Docker Engine com Compose (siga a página oficial: https://docs.docker.com/engine/install/) e depois:

```bash
sudo usermod -aG docker $USER
```

**Saia da sessão e entre de novo** para o grupo valer. Node 22+ e Claude Code:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g @anthropic-ai/claude-code
claude
```

O `claude` abre o login: entre na conta e digite `/exit`. Para o WhatsApp (pendente), instale o bun quando for usá-lo:

```bash
curl -fsSL https://bun.sh/install | bash
```

### Conferência

Em qualquer sistema, cada comando abaixo deve mostrar uma versão (os números exatos podem variar):

```bash
git --version
python --version
php -v
docker --version
docker compose version
node --version
claude --version
```

| Esperado | Se vier diferente |
|---|---|
| `Python 3.x` com x ≥ 10; `PHP 8.2.x`; `Node v22` ou maior | Versão menor: instale a certa. No Linux, o comando é `python3` se `python` não existir |
| Uma versão para cada comando | "não é reconhecido" / "command not found": o programa não foi instalado, ou (Windows) falta **reabrir o terminal** |
| `claude --version` mostra algo como `2.1.x (Claude Code)` | Veja "claude não encontrado" na etapa 15 |

---

## 3. Baixar o projeto

**Windows (PowerShell) ou Linux (bash)**, numa pasta onde você guarda projetos (ex.: `Desktop` ou `~/projetos`):

```bash
git clone --branch feat/portabilidade-windows-linux https://github.com/Luks108/hackathon.git
cd hackathon
```

Se o GitHub pedir login, entre com a conta que tem acesso ao repositório. No PowerShell, o git pode mostrar `Cloning into 'hackathon'...`
em vermelho: é só o aviso de progresso do git, não é erro.

**Conferência:**

```bash
git branch --show-current
git log --oneline -1
```

| Esperado | Se vier diferente |
|---|---|
| `feat/portabilidade-windows-linux` e uma linha de commit | Outra branch: `git switch feat/portabilidade-windows-linux`. Se a branch não existir, rode `git fetch --all` e tente de novo |
| `ls` (Linux) ou `dir` (Windows) mostra `README.md`, `chat`, `site`, `consulta`... | Você está na pasta errada: entre em `hackathon` |

Para **trocar de branch** depois (o código novo pode ter mudado de branch):

```bash
git fetch --all
git switch main
git pull
```

Troque `main` pelo nome da branch que quiser. Se o git reclamar de arquivos alterados, **não use** `git reset --hard` sem
perguntar a alguém: guarde seu trabalho com `git stash push -u -m "meu-trabalho"` antes de trocar.

---

## 4. Python e pacotes

Faça uma venv (uma "caixa" de pacotes só deste projeto).

**Windows (PowerShell), na raiz do projeto:**

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

O `Set-ExecutionPolicy -Scope Process` libera a execução de scripts **só para esta janela do PowerShell**. Ao fechar a janela, a
liberação some e nada muda no computador. Sem ele, o Windows bloqueia o `Activate.ps1` com o erro "a execução de scripts foi
desabilitada neste sistema". Em **cada janela nova** é preciso repetir os dois comandos (`Set-ExecutionPolicy` e `Activate.ps1`).
Se `python` abrir a Microsoft Store, veja a etapa 2.

**Linux (bash), na raiz do projeto:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Se o `venv` reclamar de `ensurepip` ou do pacote `python3-venv`, instale `python3-venv` (etapa 2) e **apague a pasta `.venv`
incompleta** antes de repetir (`rm -rf .venv`, ou `Remove-Item -Recurse -Force .venv` no Windows).

Com a venv ativa, o começo da linha do terminal mostra `(.venv)`. Os comandos seguintes usam apenas `python`; se não quiser ativar,
use o caminho completo (`.venv\Scripts\python` no Windows, `.venv/bin/python` no Linux).

**Conferência:**

```bash
python -c "import sys, mcp, neo4j; print(sys.prefix); print('pacotes ok')"
```

| Esperado | Se vier diferente |
|---|---|
| Um caminho que termina em `.venv` e a linha `pacotes ok` | Caminho **sem** `.venv`: a venv não está ativa, ative de novo. `ModuleNotFoundError`: rode o `pip install -r requirements.txt` com a venv ativa |

---

## 5. Configurar o `.env` e a chave do worker

O `.env` guarda senhas e chaves. **Ele nunca vai para o git** (está no `.gitignore`, junto com `site/hackathon-config.php`) e
**não se envia por WhatsApp, e-mail, chat nem nenhum canal público**. Se precisar passar uma chave a alguém, use um canal privado
e combinado. O arquivo `.env.exemplo` é só um modelo, com valores falsos (esse sim vai para o git).

### 5.1 Criar o `.env` e a configuração do site (jeito fácil)

Para desenvolvimento local, um comando cria os dois arquivos, com senhas e chave novas e **iguais onde precisam ser iguais**.
Ele não sobrescreve arquivos que já existam:

```bash
python conferir_ambiente.py --preparar
```

| Esperado | Se vier diferente |
|---|---|
| `criado:  .env` e `criado:  site/hackathon-config.php` | `já existe: ...`: o arquivo já estava lá e não foi alterado (tudo bem) |

Os arquivos criados não levam **BOM** (uma marca invisível que o PowerShell 5 e alguns editores gravam no começo do arquivo e que
**quebra** o site). Por isso este comando é mais seguro do que editar à mão.

Na **exibição ao cliente** use o `.env` com a `WORKER_KEY` do site publicado (passada pelo Lucas em canal privado) e **sem**
`API_BASE`. Para isso edite o `.env` como na seção 5.2.

### 5.2 Editar à mão (alternativa)

Só se precisar mudar algum valor. Salve sempre como **UTF-8 sem BOM** (no VS Code, canto inferior direito: *UTF-8*; no Bloco de
Notas do Windows 11 o padrão já é UTF-8 sem BOM). Não use `Set-Content -Encoding utf8` do PowerShell 5: ele grava BOM.

**Windows (PowerShell):**

```powershell
notepad .env
notepad site\hackathon-config.php
```

**Linux (bash):**

```bash
nano .env
nano site/hackathon-config.php
```

Se os arquivos ainda não existem, crie a partir dos modelos antes:

```bash
cp .env.exemplo .env
cp site/hackathon-config.exemplo.php site/hackathon-config.php
```

(No Windows, `Copy-Item` no lugar de `cp`.) Para gerar uma senha ou chave aleatória:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

No `site/hackathon-config.php`, troque **apenas** a linha `const WORKER_KEY = '...'` pela **mesma `WORKER_KEY` do `.env`** (entre aspas
simples, sem espaços). Não mexa nas linhas do banco: elas já combinam com o Docker local.

### 5.3 O que cada variável significa

| Variável | Obrigatória? | De onde vem o valor | Se faltar ou estiver errada |
|---|---|---|---|
| `NEO4J_SENHA` | **Sim** | Gerada pelo `--preparar` (ou invente uma). Vale só no seu Neo4j local. Ela é gravada no Neo4j **na primeira vez que ele sobe**: trocar depois no `.env` não troca a do banco | O Docker do Neo4j nem sobe (`defina NEO4J_SENHA no .env`); se não bater com a do banco, o carregamento dá `Unauthorized` |
| `CHAVE_PF` | **Sim** para extrair dados reais; com os dados fictícios o carregamento não a usa, mas mantenha preenchida | Você inventa | `KeyError: 'CHAVE_PF'` ao extrair dados reais |
| `NEO4J_URI` | **Sim** | Deixe `bolt://127.0.0.1:7689` | `KeyError: 'NEO4J_URI'` ao carregar os dados |
| `BRUTO` | Não | Deixe `fixtures/exemplo/bruto` (dados fictícios). Caminho relativo vale a partir da raiz do projeto | O agente diz que o hash da prova "não confere" |
| `WORKER_KEY` | **Sim** (para o chat) | Gerada pelo `--preparar` (24+ caracteres). **Tem de ser igual** à de `site/hackathon-config.php`. Na exibição: a do site publicado, passada pelo Lucas em canal privado | O worker não inicia (`KeyError: 'WORKER_KEY'`); se for diferente da do site, o worker mostra `site: API respondeu 401` sem parar e as perguntas ficam paradas |
| `API_BASE` | Não, mas **recomendada local** | Local: `http://127.0.0.1:8080`. Na exibição: **apague a linha** | **Sem ela, o worker aponta para o site PUBLICADO**, e não para o seu |
| `AGENTE_MODELO` | Não | Padrão `claude-opus-5-5` | Usa o padrão |
| `AGENTES_SITE` | Não | Padrão `3` perguntas ao mesmo tempo | Usa o padrão |
| `AGENTE_LIMITE_S` | Não | Padrão `110` segundos por pergunta | Usa o padrão |
| `AGENTE_PYTHON`, `CLAUDE_BIN` | Não | Caminhos completos, só se a detecção automática falhar | O projeto procura sozinho (`.venv` e `claude`) |
| `WHATSAPP_STATE_DIR` | Não | Pasta de estado do gateway | Usa `~/.claude/channels/whatsapp-hackathon` |


O site PHP **não lê** o `.env`: ele lê `site/hackathon-config.php`, por isso a `WORKER_KEY` existe nos dois arquivos. O número do
WhatsApp também **não** fica no `.env`: veja a etapa 11. Nas linhas opcionais, apague o `#` só se quiser mudar o padrão.

### Conferência

```bash
python conferir_ambiente.py
```

| Esperado | Se vier diferente |
|---|---|
| Todas as linhas `OK` e, no fim, `Tudo pronto.` | Cada `FALTA` traz logo abaixo o que fazer. `AVISO` pode ser ignorado por enquanto (por exemplo, `bun` ausente) |
| `site/hackathon-config.php existe e a WORKER_KEY confere com o .env` | `WORKER_KEY ... DIFERENTE`: copie a chave do `.env` para o arquivo do site |
| | `foi gravado com BOM`: o arquivo foi salvo com uma marca invisível no começo. Apague-o e rode `python conferir_ambiente.py --preparar` |

Esse comando não mostra nenhum segredo e não altera nada.

---

## 6. Subir os bancos de dados

O Docker Desktop (Windows) precisa estar aberto. Rode, um de cada vez, na raiz do projeto:

```bash
docker compose -f site/dev/docker-compose.yml up -d --wait
docker compose --env-file .env -f infra/docker-compose.yml up -d --wait neo4j
```

A primeira vez baixa as imagens e leva alguns minutos. O `--wait` só devolve o terminal quando o banco está saudável.

**Conferência:**

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

| Esperado | Se vier diferente |
|---|---|
| `hackathon-site-db` com `Up ... (healthy)` e porta `127.0.0.1:3307->3306` | `Exited` ou ausente: veja `docker logs hackathon-site-db` |
| `hackathon-neo4j` com `Up ... (healthy)` e portas `7476` e `7689` | Porta em uso: veja "porta já em uso" na etapa 15 |
| Erro "cannot connect to the Docker daemon" | O Docker não está aberto (Windows) ou o serviço está parado (Linux: `sudo systemctl start docker`) |

---

## 7. Carregar os dados fictícios

Com a venv ativa:

```bash
python coleta/carregar_neo4j.py --zerar --exemplo
```

Os dados são fictícios (`fixtures/exemplo`). O `--zerar` apaga o que já estava no grafo.

**Conferência:** a saída deve listar a contagem de cada tipo:

```text
evidencias: 10
fornecedores: 6
processos: 1
contratos: 5
sancoes: 2
execucoes: 2
```

| Esperado | Se vier diferente |
|---|---|
| As seis linhas acima (os números podem mudar se os dados de exemplo mudarem) | `Connection refused` / `ServiceUnavailable`: o Neo4j ainda está iniciando ou a `NEO4J_URI` está errada. Espere 30 s e repita |
| | `KeyError: 'NEO4J_URI'` ou `NEO4J_SENHA`: o `.env` não foi preenchido (etapa 5) |
| | `Neo.ClientError.Security.Unauthorized`: a `NEO4J_SENHA` do `.env` mudou depois de o Neo4j ser criado. Apague o volume (`docker compose --env-file .env -f infra/docker-compose.yml down -v`) e suba de novo |

---

## 8. Subir o site

### 8.1 Criar as tabelas e o administrador de teste

**Só em desenvolvimento.** Este administrador e esta senha **não existem** no site publicado.

```bash
php site/setup.php admin@local.test "Admin Local" senha-local-123
```

**Conferência:**

| Esperado | Se vier diferente |
|---|---|
| `admin pronto: admin@local.test` e `tabelas ok (7), planos: 2` | `could not find driver`: falta a extensão `pdo_mysql` do PHP (etapa 2) |
| | `Connection refused` ou `getaddrinfo`: o MariaDB não está no ar (etapa 6) |
| | `php` não reconhecido (Windows): feche e reabra o PowerShell, ou use o caminho completo do `php.exe` |

### 8.2 Ligar o site

Este comando **fica rodando** e ocupa a janela. Deixe-o aberto e use **outra janela** para os próximos passos (se for Windows, na
nova janela repita o `Set-ExecutionPolicy` e o `Activate.ps1` da etapa 4).

```bash
php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php
```

Em outra janela, na raiz do projeto:

**Windows (PowerShell):**

```powershell
Invoke-WebRequest http://127.0.0.1:8080/api/saude -UseBasicParsing | Select-Object -ExpandProperty Content
```

**Linux (bash):**

```bash
curl http://127.0.0.1:8080/api/saude
```

| Esperado | Se vier diferente |
|---|---|
| `{"ok":true,"hora":"..."}` | Recusou a conexão: o `php -S` não está rodando, ou a porta 8080 está em uso (etapa 15) |
| Abrir `http://127.0.0.1:8080` no navegador mostra a página inicial "FornexIA" com os planos | Página em branco ou erro 500: olhe a janela do `php -S`, que mostra o erro |

---

## 9. Subir o worker e conversar com o agente

### 9.1 Testar o agente sozinho (sem o site)

Com a venv ativa e o Neo4j com os dados (etapa 7):

```bash
python chat/agente.py estado "Quais contratos temos na base?"
```

**Conferência:** em 10 a 40 segundos a saída mostra linhas `texto ...` (pedaços da resposta), depois `fim {"duracao_ms": ...}`,
depois `---` e a resposta completa em português, citando contratos de **Garanhuns** (fictícios).

| Esperado | Se vier diferente |
|---|---|
| `fim {...}` e a resposta | `erro {...}` ou nada: veja "agente não responde" na etapa 15 |
| A resposta diz que os arquivos guardados **conferem** com o original | "não bate mais com o hash": o `BRUTO` está errado ou você está numa versão antiga do código |

Cada pergunta ao agente **gasta o seu modelo**. Não rode em laço.

### 9.2 Ligar o worker

Em uma janela nova (com a venv ativa), **deixe rodando**:

```bash
python chat/worker.py
```

**Conferência:** deve aparecer logo:

```text
HH:MM:SS worker no ar: http://127.0.0.1:8080/api com 3 agentes no site
```

| Esperado | Se vier diferente |
|---|---|
| A linha acima, com `127.0.0.1:8080` | Aponta para outro endereço (por exemplo `hackathon.figueiredo.dev`): faltou `API_BASE` no `.env` e o worker está atendendo o site **publicado**. Pare (`Ctrl+C`), corrija e suba de novo |
| | `KeyError: 'WORKER_KEY'`: falta a chave no `.env` (etapa 5) |
| | O log repete `site: API respondeu 401`: a `WORKER_KEY` do `.env` difere da do site. Deixe as duas iguais, reinicie o site e o worker |

Para ver a resposta "como se fosse WhatsApp", sem enviar nada:

```bash
python chat/worker.py --simular "Existe alguma sanção para algum fornecedor?"
```

### 9.3 Conversar pelo site

1. Abra `http://127.0.0.1:8080/chat.html`.
2. Clique em **Criar conta**, preencha nome, e-mail (qualquer um, ex.: `eu@teste.local`) e senha com 8+ caracteres.
3. Pergunte: `Existe alguma sanção para algum fornecedor?`

| Esperado | Se vier diferente |
|---|---|
| A resposta aparece aos poucos, em cerca de 10 a 30 s, citando a Construtora Exemplo (dado fictício) e com a fonte | "Posição na fila" que não anda: o worker não está rodando ou a chave difere |
| | "Não consegui concluir agora": veja a janela do worker, que mostra o erro |

---

## 10. Teste de fumaça no navegador

Um "teste de fumaça" abre as páginas num navegador de verdade (sem janela), espera o JavaScript rodar e confere que a tela certa
apareceu. Com o site no ar (etapa 8) e a venv ativa:

```bash
python site/dev/fumaca_navegador.py
```

**Conferência:**

```text
navegador: ...msedge.exe (ou chrome, ou chromium)
OK     /
OK     /chat.html
OK     /conta.html
OK     /admin.html

Tudo certo.
```

| Esperado | Se vier diferente |
|---|---|
| Quatro linhas `OK` e `Tudo certo.` | `FALHOU /` com "não mostrou os planos": o JavaScript quebrou ou `/api/planos` não respondeu. Abra a página à mão e aperte `F12` para ver o erro |
| | `FALHOU ... o navegador não abriu a página`: o site não está no ar |
| | "Não achei Chrome, Edge nem Chromium": instale um deles ou defina `NAVEGADOR` com o caminho do executável |

**O teste não funciona no Opera:** ele precisa do modo de depuração do Chromium (`--dump-dom`), que o Opera não oferece. O script
recusa o Opera e pede Chrome, Edge ou Chromium. Para o resto do guia, você pode *usar* o site no Opera normalmente; só o teste
automático é que não roda nele.

O teste cobre só as páginas abertas, sem login. Para o fluxo completo (cadastro, pergunta e resposta), faça a etapa 9.3.

---

## 11. WhatsApp (pendente)

> **PENDENTE.** A conexão do WhatsApp está sendo resolvida por fora e **ainda não foi testada de ponta a ponta** neste computador.
> O que existe: o gateway compila e as dependências instalam. O que **não** foi feito: parear um número e trocar mensagens.
> Pule esta etapa; o site e o chat funcionam sem ela.

Quando for a hora, o fluxo previsto é este. **Um comando por linha. O número de telefone nunca fica neste documento nem no git:**
ele vem por canal privado.

**1. Instalar as dependências (uma vez)** — Windows ou Linux:

```bash
cd canal-whatsapp
bun install
```

**2. Definir o número a parear** (formato `55` + DDD + número, só dígitos; use um chip **de teste**, nunca o número que o notebook
da exibição usa, porque o WhatsApp só aceita uma conexão por número).

Windows (PowerShell):

```powershell
$env:WA_PAIR_PHONE = "SEU_NUMERO_DE_TESTE"
```

Linux (bash):

```bash
export WA_PAIR_PHONE="SEU_NUMERO_DE_TESTE"
```

**3. Ligar o gateway** (ele imprime um código de 8 letras; no celular: WhatsApp → Aparelhos conectados → Conectar com número de
telefone → digite o código):

```bash
bun gateway.ts
```

**4. Em outra janela, liberar quem pode falar com o bot** (o primeiro número liberado vira o dono):

```bash
cd canal-whatsapp
bun acesso.ts add SEU_NUMERO_DE_TESTE
bun acesso.ts status
```

**5. Com o gateway ligado, rode o worker** (etapa 9.2) e mande uma mensagem do número liberado.

**Conferência (quando for feita):** `bun acesso.ts status` deve indicar o gateway como ativo, e o worker mostra `whatsapp:` no log
ao receber a mensagem. Enquanto a etapa estiver pendente, `bun acesso.ts status` mostra `gateway nunca rodou`: é o esperado.

---

## 12. Testes automáticos

Rode nesta ordem, com a venv ativa e os bancos no ar. **Pare o worker antes de rodar os testes da API:** ele compartilha o banco
e levaria perguntas dos testes, derrubando um deles.

```bash
python -m unittest discover -s consulta/testes
python -m unittest discover -s chat/testes
python site/dev/test_api.py
```

| Comando | Esperado | Se vier diferente |
|---|---|---|
| `consulta/testes` | `Ran 48 tests` e `OK` | `skipped=...`: o Neo4j está parado ou sem os dados (etapas 6 e 7). Falha: leia o nome do teste |
| `chat/testes` | `Ran 4 tests` e `OK` | |
| `site/dev/test_api.py` | `Ran 78 tests` e `OK` (leva uns 40 s) | `php não encontrado`: defina `PHP_BIN` (abaixo). `servidor ... não subiu`: o MariaDB não está no ar. Uma falha em `dois_pedidos_ao_mesmo_tempo...`: o worker estava rodando |

`PHP_BIN` no Windows (PowerShell), se o PHP não estiver no PATH:

```powershell
$env:PHP_BIN = "C:\caminho\para\php.exe"
```

---

## 13. Linux: deixar tudo como serviço

Na máquina da exibição, o worker (e, quando o WhatsApp estiver resolvido, o gateway) sobem sozinhos no boot, como serviços do
**seu usuário** (`systemctl --user`).

**1. Copiar os arquivos de serviço** (na raiz do projeto):

```bash
mkdir -p ~/.config/systemd/user
cp chat/chat-worker.service ~/.config/systemd/user/
```

**2. Ajustar os caminhos.** Os arquivos trazem o caminho do notebook do Lucas. Abra e troque `WorkingDirectory`, `ExecStart` e os
caminhos do `PATH` pelos da sua máquina (use o caminho completo da pasta do projeto):

```bash
nano ~/.config/systemd/user/chat-worker.service
```

O `ExecStart` deve apontar para `.venv/bin/python chat/worker.py` **dentro da pasta do projeto**, e o `PATH` deve incluir a pasta
onde está o `claude` (descubra com `which claude`).

**3. Ligar e habilitar no boot:**

```bash
systemctl --user daemon-reload
systemctl --user enable --now chat-worker
sudo loginctl enable-linger $USER
```

O `enable-linger` faz os serviços do usuário subirem no boot mesmo sem ninguém ter entrado na sessão.

**4. Conferir o status e os logs:**

```bash
systemctl --user status chat-worker
journalctl --user -u chat-worker -f
```

| Esperado | Se vier diferente |
|---|---|
| `Active: active (running)` e, no log, `worker no ar: ... com 3 agentes no site` | `failed` ou `activating (auto-restart)`: o log mostra o erro; quase sempre é caminho errado no `ExecStart` ou `.env` sem `WORKER_KEY` |
| Depois de reiniciar o computador, o serviço está `active` sem você fazer nada | Faltou `loginctl enable-linger` |

Comandos úteis: `systemctl --user restart chat-worker`, `systemctl --user stop chat-worker`, `systemctl --user disable chat-worker`.

**Gateway do WhatsApp (pendente).** Quando o pareamento estiver resolvido, o procedimento é o mesmo, com o arquivo
`canal-whatsapp/wa-gateway.service`:

```bash
cp canal-whatsapp/wa-gateway.service ~/.config/systemd/user/
nano ~/.config/systemd/user/wa-gateway.service
systemctl --user daemon-reload
systemctl --user enable --now wa-gateway
systemctl --user status wa-gateway
```

O `ExecStart` do gateway usa o caminho do `bun` (descubra com `which bun`). **Não habilite o `wa-gateway` antes de parear o número.**
Nunca deixe o worker rodando como serviço e, ao mesmo tempo, à mão no terminal: os dois responderiam à mesma pergunta.

---

## 14. Ordem de subida e sinais de que está no ar

Suba nesta ordem. O que vem depois depende do que vem antes.

| # | Serviço | Como subir | Sinal de que está no ar |
|---|---|---|---|
| 1 | Docker | Abrir o Docker Desktop (Windows) / `sudo systemctl start docker` (Linux) | `docker ps` responde sem erro |
| 2 | MariaDB do site | `docker compose -f site/dev/docker-compose.yml up -d --wait` | `hackathon-site-db` `(healthy)`, porta `3307` |
| 3 | Neo4j | `docker compose --env-file .env -f infra/docker-compose.yml up -d --wait neo4j` | `hackathon-neo4j` `(healthy)`, porta `7689` |
| 4 | Dados fictícios | `python coleta/carregar_neo4j.py --zerar --exemplo` | Seis contagens (`evidencias: 10` ... `execucoes: 2`) |
| 5 | Site | `php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php` | `http://127.0.0.1:8080/api/saude` → `{"ok":true,...}` |
| 6 | Worker | `python chat/worker.py` | `worker no ar: http://127.0.0.1:8080/api com 3 agentes no site` |
| 7 | WhatsApp (pendente) | `bun gateway.ts` | `bun acesso.ts status` ativo |

Para conferir tudo de uma vez (programas, `.env`, chaves e portas):

```bash
python conferir_ambiente.py --servicos
```

| Esperado | Se vier diferente |
|---|---|
| `OK` em MariaDB (3307), Neo4j (7689), Site (8080) e `site responde em /api/saude` | Cada `FALTA` mostra o comando que sobe aquele serviço |

Para desligar, `Ctrl+C` nas janelas do site e do worker e:

```bash
docker compose -f site/dev/docker-compose.yml stop
docker compose --env-file .env -f infra/docker-compose.yml stop
```

---

## 15. Problemas comuns

**O `python` abriu a Microsoft Store (Windows).**
O Python não está instalado, e o Windows oferece a Loja. Feche a Loja e instale com `winget install --id Python.Python.3.12 -e`;
depois feche e reabra o PowerShell. Se a Loja continuar abrindo, desligue os "aliases de execução" do Python (etapa 2).

**`Activate.ps1 não pode ser carregado porque a execução de scripts foi desabilitada`.**
É a política de execução do Windows. Rode `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` e ative a venv de novo.
Vale só para aquela janela; repita em cada janela nova.

**`php` não é reconhecido logo depois de instalar com o winget.**
O PATH só é atualizado para terminais abertos *depois* da instalação. Feche o PowerShell (e o VS Code, se estiver usando o terminal
dele) e abra de novo. Se ainda falhar, use o caminho completo do `php.exe` ou defina `PHP_BIN`.

**`npm.ps1 não pode ser carregado` ao instalar o `claude` (Windows).**
O `npm` do PowerShell é um script bloqueado pela mesma política. Use `npm.cmd install -g @anthropic-ai/claude-code`, ou libere só
aquela janela com `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

**`claude` não encontrado, ou pede para entrar na conta.**
Instale (etapa 2) e rode `claude` uma vez para fazer o login. No Windows, o projeto também acha o `claude` da extensão do VS Code.
Se estiver num caminho estranho, ponha o caminho completo em `CLAUDE_BIN` no `.env`.

**`python3 -m venv` falha com "ensurepip is not available" (Ubuntu/Debian).**
Falta o pacote: `sudo apt install -y python3-venv`. Apague a `.venv` pela metade (`rm -rf .venv`) e crie de novo.

**A porta já está em uso (8080, 3307, 7689 ou 7476).**
Outro programa (ou uma cópia antiga deste) usa a porta. Para descobrir quem:

Windows (PowerShell):

```powershell
netstat -ano | Select-String ":8080"
```

Linux (bash):

```bash
ss -ltnp | grep 8080
```

Pare o processo (no Windows, `Stop-Process -Id NUMERO_DO_PID`; no Linux, `kill NUMERO_DO_PID`) ou, para o site, suba em outra porta
(`php -S 127.0.0.1:8081 ...`) e ponha o mesmo endereço em `API_BASE`.

**O worker diz `KeyError: 'WORKER_KEY'`.**
Falta a chave no `.env`. Preencha (etapa 5) e suba de novo. Depois, confira com `python conferir_ambiente.py`.

**O worker sobe, mas as perguntas ficam paradas (o log repete `site: API respondeu 401`).**
A `WORKER_KEY` do `.env` é diferente da de `site/hackathon-config.php`. Deixe as duas iguais e **reinicie o site e o worker**.

**O worker atende o site errado.**
Faltou `API_BASE=http://127.0.0.1:8080` no `.env`: sem ela o worker usa o site publicado.

**O Docker diz `cannot connect to the Docker daemon` / `dockerDesktopLinuxEngine`.**
O Docker não está rodando. Windows: abra o Docker Desktop e espere "Engine running". Linux: `sudo systemctl start docker` (e, se der
"permission denied", você ainda não está no grupo `docker`: etapa 2, e saia e entre na sessão).

**O Neo4j dá `Connection refused` ao carregar os dados.**
Ele leva até um minuto para ficar pronto. Rode `docker ps`: espere `(healthy)` e repita.

**O agente não responde, ou termina com erro.**
Rode `python chat/agente.py estado "Olá"` e leia a mensagem. Causas comuns: o `claude` não está logado (rode `claude`), o Neo4j está
parado, ou a internet caiu. O limite por pergunta é `AGENTE_LIMITE_S` (110 s).

**Os testes da API falham com "servidor ... não subiu".**
O MariaDB não está no ar, ou o `php` não foi achado. Defina `PHP_BIN` e confira `docker ps`.

**`deploy.sh` ou outro `.sh` dá `bad interpreter` / `^M` no Linux.**
O arquivo foi gravado com fim de linha do Windows. O `.gitattributes` evita isso em clones novos; num clone antigo,
rode `git add --renormalize .` ou clone de novo.

**A API devolve algo estranho (`Unexpected UTF-8 BOM` no worker, JSON quebrado, "headers already sent") depois de editar a configuração.**
O `site/hackathon-config.php` (ou o `.env`) foi salvo com **BOM**, uma marca invisível no começo do arquivo. O `PowerShell 5`
(`Set-Content -Encoding utf8`) e alguns editores fazem isso. Rode `python conferir_ambiente.py`: ele acusa o BOM. Apague o arquivo e rode
`python conferir_ambiente.py --preparar`, ou salve de novo como "UTF-8 sem BOM".

**Deu tudo errado e quero recomeçar.**
Pare tudo (etapa 14), `docker compose -f site/dev/docker-compose.yml down -v` e `docker compose --env-file .env -f infra/docker-compose.yml down -v`
(isso **apaga** os dados dos bancos locais), apague a pasta `.venv` e refaça a partir da etapa 4.

---

## 16. Cuidados de portabilidade

Regras para quem for mexer no código, para ele continuar rodando nos dois sistemas.

- `*.sh` e `*.service` são sempre gravados com fim de linha LF (`.gitattributes`). Um `deploy.sh` com CRLF não roda no Linux.
  *(Importa na etapa 3, ao clonar no Windows, e na etapa 13.)*
- Não escreva caminhos `.venv/bin/...` no código. Use `agente.PYTHON` e `agente.CLAUDE`, que já tratam Windows e Linux.
  *(Importa nas etapas 4 e 9: é por isso que o mesmo `chat/worker.py` roda nos dois.)*
- Para trocar um arquivo de forma atômica, use `os.replace`: `Path.rename` falha no Windows se o destino já existe.
  *(Importa na etapa 11, na fila de saída do WhatsApp.)*
- Arquivo temporário que outro processo vai abrir não pode usar `NamedTemporaryFile` com `delete=True`: no Windows ele fica
  trancado. *(Importa na etapa 9: o agente passa a configuração do MCP ao `claude` por um arquivo temporário.)*
- Caminhos relativos no `.env` (como `BRUTO`) valem a partir da raiz do projeto, e não da pasta em que o processo roda.
  *(Importa na etapa 5.)*
