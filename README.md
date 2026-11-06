# Histórico de fornecedor com prova

Projeto do **Desafio 1 — Portal Inteligente de Transparência com IA** do Hack Garanhuns Tech 2026.

Consulta em linguagem natural a dados públicos de contratação. Toda resposta aponta para o trecho literal
da fonte, e cada perfil vê só o que está autorizado a ver.

> **Estado:** extração, grafo, consultas com filtro de perfil, registro de consultas, catálogo de ataques **e o site com contas,
> chat em fila e administração** estão prontos e **testados** (43 testes de consulta e 78 testes da API do site). Ainda falta o
> agente isolado (worker) ligado ao site e os ataques rodados com o modelo real. Veja
> [Onde estamos no desafio](#onde-estamos-no-desafio), [Site e chat (Dev A)](#site-e-chat-dev-a) e [Pendências conhecidas](#pendências-conhecidas).
> Detalhes do site e do chat: [spec](docs/specs/001-site-e-chat/spec.md), [plano técnico](docs/specs/001-site-e-chat/plan.md) e [tasks](docs/specs/001-site-e-chat/tasks.md).

## Estrutura

| Pasta | O quê |
|---|---|
| `coleta/` | Extrai fatos com evidência da captura bruta e carrega no Neo4j |
| `consulta/` | Servidor MCP `transparencia`, perfis de acesso (`perfis.json`), testes e página do grafo |
| `consulta/testes/` | Testes de segurança: código offline, isolamento no Neo4j real e verificador de respostas |
| `fixtures/` | Dados fictícios para desenvolver sem a captura real (três entes, uma pessoa física, um texto malicioso) |
| `esquema/`, `infra/` | Restrições do grafo e Docker Compose local |
| `canal-whatsapp/` | Gateway Baileys, canal MCP e controle de acesso |
| `site/` | Site PHP 8.2 + MariaDB: páginas, API (`public_html/api/`), `setup.php` e `deploy.sh` para a Hostinger |
| `site/dev/` | Ambiente local do site: Docker do banco, roteador do servidor embutido do PHP, worker falso e os 78 testes da API |
| `inferencia/`, `planilha/` | Ferramentas de visão, áudio e planilha, herdadas do modelo do hackathon |
| `docs/seguranca/` | **Catálogo de ataques de prompt** e proteções |
| `docs/apresentacao/` | Página de demonstração para o cliente e gerador da base de conhecimento |
| `docs/` | Backlog, tarefas, resultados dos testes de segurança |
| `logs/` | Registro de consultas (`consultas.jsonl`), não versionado |

## Onde estamos no desafio

| Requisito do desafio | Situação | Onde |
|---|---|---|
| Captura de ao menos um portal estadual | **Parcial.** Garanhuns (municipal) capturado. Do Estado de PE, só o CSV de sanções. A coleta dos painéis estaduais não foi testada | `coleta/` |
| Normalização e catalogação | **Pronto** | `coleta/extrair.py`, `esquema/neo4j.cypher` |
| Controle de acesso por estado e perfil | **Pronto na camada de dados, testado.** Três perfis (Município, Estado de PE, outro estado fictício) | `consulta/perfis.json`, `consulta/testes/test_acesso_neo4j.py` |
| LLM restrita aos dados autorizados | **Dados testados.** O agente isolado que roda o modelo ainda não existe | `docs/specs/001-site-e-chat/tasks.md` (B01 a B07) |
| Registro de consultas e fontes | **Pronto** no servidor MCP. CPF digitado é mascarado no log | `logs/consultas.jsonl` |
| RAG com citação de fonte | **Pronto no backend:** cada fato traz trecho, data e hash conferível. A busca em documentos existe só na página de demonstração | `conferir_evidencia`, `docs/apresentacao/` |
| Multi-tenant | **Testado** com três entes: o mesmo CNPJ tem fatos em cada um, e cada perfil vê só os seus | `fixtures/gerar_exemplo.py` |
| Proteção contra ataques de prompt | **20 ataques catalogados.** A camada de dados está testada. Os testes com o modelo real estão pendentes | [`docs/seguranca/ataques-de-prompt.md`](docs/seguranca/ataques-de-prompt.md) |
| Site com contas, planos e chat | **Pronto e testado com worker falso.** Cadastro, login, assinatura, fila de perguntas, telefones do WhatsApp e tela de administração. O deploy real na Hostinger ainda não foi feito | [Site e chat (Dev A)](#site-e-chat-dev-a) |

## Site e chat (Dev A)

Parte do Dev A: tudo que o usuário vê no navegador e a API PHP que o worker do Dev B consome.

### Páginas

| Página | Para quê |
|---|---|
| `/` (`index.html`) | Apresentação, planos (lidos da API), modelo de negócios e o assistente flutuante |
| `/chat.html` | Entrar ou criar conta e conversar com o assistente. O assistente flutuante da página inicial é este mesmo chat dentro de um `iframe` (`?embutido=1`) |
| `/conta.html` | Dados da conta, plano e telefones de WhatsApp (até 3), com o estado de cada um |
| `/admin.html` | Fila de telefones: aprovar, recusar, bloquear. Só para administradores |

### Como o chat funciona

O site não fala com o modelo. Ele guarda a pergunta numa **fila** e o **worker** (Dev B), que roda no notebook, busca a próxima,
conversa com o agente e devolve os eventos aos poucos. O navegador consulta os eventos a cada 0,7 s.

- Uma pergunta aberta por conta (trava com `FOR UPDATE`). Pergunta parada na fila por mais de 120 s, ou em processamento por mais
  de 180 s, é encerrada com uma mensagem legível. O navegador desiste após 130 s.
- A reserva da pergunta pelo worker é atômica (`UPDATE` condicional), então dois workers nunca pegam a mesma.
- Todo texto vindo do agente ou da fonte é desenhado com `textContent`, nunca como HTML. O worker falso inclui de propósito uma
  fonte com URL `javascript:` para provar que ela não vira link.
- **Demonstração livre:** na demonstração ao cliente não há etapa de escolha de plano. Os planos aparecem só como informação, e
  quem se cadastra já conversa. A etapa existe no código, desligada pela constante `ESCOLHER_PLANO` em `assets/chat.js`. Quando o
  produto for vendido, é só ligá-la.

### API

Todas as rotas ficam em `/api/...`. O contrato completo (formatos, códigos de erro) está no
[plano técnico](docs/specs/001-site-e-chat/plan.md).

| Grupo | Rotas |
|---|---|
| Conta | `GET /me`, `POST /cadastro`, `POST /login`, `POST /logout` |
| Planos | `GET /planos`, `POST /assinatura` |
| Chat | `POST /perguntas`, `GET /perguntas/aberta`, `GET /perguntas/{id}/eventos` |
| Telefones | `GET`/`POST /telefones`, `DELETE /telefones/{id}` |
| Administração | `GET /admin/telefones`, aprovar e revogar |
| Worker (chave própria) | `GET /worker/proxima`, `POST /worker/perguntas/{id}/eventos`, `GET /worker/telefones` |

Planos de demonstração (valores ainda não validados): **Município** R$ 990, 300 perguntas, R$ 1,50 por excedente, vê só
`pe-garanhuns`; **Estado** R$ 1.990, 1.000 perguntas, R$ 1,50 por excedente, vê `pe-estado` e `pe-garanhuns`.

### Segurança do site

- Cookie de sessão `hsid` com `HttpOnly`, `SameSite=Lax` e `Secure` (menos com `AMBIENTE='dev'`); o id é trocado no login.
- **CSRF:** toda escrita exige o cabeçalho `X-CSRF-Token`, obtido em `GET /api/me`.
- **Limite de tentativas de login:** 429 com `Retry-After` de 900 s. O login leva o mesmo tempo para e-mail existente e inexistente
  (não revela quais e-mails têm conta).
- Consultas SQL sempre parametrizadas. Senhas com hash. O worker se autentica com uma chave própria (`WORKER_KEY`, mínimo de 24
  caracteres), separada das sessões de usuário.
- Telefones normalizados para `55` + DDD + `9` + 8 dígitos; caracteres fora de dígitos, espaço, parênteses, `+` e `-` são recusados.
  Máximo de 3 por conta; aprovação registra quem aprovou e quando (`aprovado_por`, `atualizado_em`).
- Sem administrador padrão com senha fixa em produção. `setup.php` só roda pela linha de comando e, fora do modo `dev`, recusa
  senha de administrador com menos de 12 caracteres ou na lista de senhas comuns.
- `deploy.sh` escapa os valores gravados no arquivo de configuração (uma senha com `'` não quebra mais) e exige `WORKER_KEY`.

### Como rodar o site localmente

Passo a passo (PHP, banco em Docker, worker falso, usuário administrador de teste) em [`site/dev/README.md`](site/dev/README.md).
Testes da API, com banco e servidor locais no ar:

```bash
python site/dev/test_api.py          # 78 testes
```

Além do comportamento normal, eles cobrem concorrência (80 perguntas com 12 workers; 25 rodadas com 6 sessões) e foram validados por
**mutação**: 17 proteções removidas de propósito, e os testes falharam em todas as 17.

### Tasks do Dev A

| Task | O quê | Situação |
|---|---|---|
| A01 | Tabelas e planos no `setup.php` | ✅ |
| A02 | `POST /api/cadastro` | ✅ |
| A03 | Proteger login e escrita (CSRF, limite, tempo constante) | ✅ |
| A04 | Planos e assinatura | ✅ (a etapa de escolha no chat fica desligada na demonstração) |
| A05 | `POST /api/perguntas` | ✅ |
| A06 | Leitura de eventos | ✅ |
| A07 | Rotas do worker | ✅ |
| A08 | Rotas de telefone do usuário | ✅ |
| A09 | Aprovação do administrador | ✅ |
| A10 | Layout comum e landing | 🟡 Landing e cabeçalho comum prontos. O chat ainda usa cabeçalho próprio |
| A11 | Planos na landing | ✅ |
| A12 | Modelo de negócios | ✅ |
| A13 | Sobre nós | ⏳ Aguardando fotos e textos da equipe |
| A14 | Login, cadastro e conta | ✅ |
| A15 | Chatbox | ✅ |
| A16 | Tela do administrador | ✅ |

**Resumo:** 14 de 16 prontas, 1 parcial (A10) e 1 pendente por falta de material (A13). As tasks B01 a B10 (worker e WhatsApp) são
do Dev B, e o deploy/dados são do Lucas.

### O que não foi verificado no site

- **Deploy real na Hostinger.** `deploy.sh` foi testado com `ssh`/`rsync` falsos e valores hostis, não no servidor. Falta conferir
  `.htaccess`, repasse de cabeçalhos, cookie `Secure` em HTTPS e a versão do MariaDB.
- **Celular de verdade**, teclado virtual e leitor de tela. O layout foi testado em navegador sem interface, com largura de celular.
- **Worker real.** Todo o fluxo do chat foi testado com o worker falso (`site/dev/worker_falso.py`).

## Como rodar

Crie um `.env` na raiz com `NEO4J_SENHA`, `CHAVE_PF`, `NEO4J_URI=bolt://127.0.0.1:7689` e `BRUTO` (veja `.env.exemplo`).
A captura bruta não é versionada, porque pode conter dados pessoais.

**Com dados fictícios** (não precisa da captura):

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt     # no Windows: .venv\Scripts\pip
docker compose --env-file .env -f infra/docker-compose.yml up -d neo4j
python coleta/carregar_neo4j.py --zerar --exemplo
python -m unittest discover -s consulta/testes -v                     # 43 testes
```

**Com a captura real:**

```bash
.venv/bin/python coleta/extrair.py
.venv/bin/python coleta/estado.py contratos 2024     # intervalo de 10 s entre pedidos
.venv/bin/python coleta/estado.py medir
.venv/bin/python coleta/amostra.py                   # gera dados/amostra/cnpjs.txt
.venv/bin/python coleta/estado.py execucao 2024 dados/amostra/cnpjs.txt
.venv/bin/python coleta/estado.py execucao 2025 dados/amostra/cnpjs.txt
.venv/bin/python coleta/extrair.py && .venv/bin/python coleta/amostra.py
.venv/bin/python coleta/carregar_neo4j.py --zerar --amostra
```

### Perfis de acesso

O perfil (quais entes e se vê dado pessoal) **nunca** é argumento de tool: entra no ambiente do servidor MCP.

```bash
python consulta/perfis.py                       # lista: municipio, estado, estado-exemplo
python consulta/perfis.py estado --config       # configuração MCP pronta para o agente
```

Uma sessão do agente carrega **um** servidor `transparencia`, com **um** perfil. Dois servidores na mesma sessão deixariam o
modelo escolher o mais permissivo (AP-19).

### Registro de consultas

Cada chamada de tool grava uma linha em `logs/consultas.jsonl`: horário, sessão, perfil, entes, tool, argumentos, quantos
resultados e quais evidências. Tentativas recusadas também entram. Defina `TRANSPARENCIA_SESSAO` para ligar as consultas à
pergunta que as originou.

### Testar ataques

O [catálogo](docs/seguranca/ataques-de-prompt.md) tem 20 ataques com exemplos de prompts, a camada que barra cada um e o status.
O resultado dos testes fica em [`docs/testes-seguranca.md`](docs/testes-seguranca.md). Para conferir uma resposta do agente real:

```bash
python consulta/testes/verificar_resposta.py municipio --resposta resposta.txt --log logs/consultas.jsonl --sessao ataque-03
```

### Página de demonstração para o cliente

`docs/apresentacao/demo-chat.html` abre direto no navegador. O chat dela é **simulado** (respostas por regras, dados fictícios) e
a própria página avisa isso. Ela responde também a partir de documentos da empresa:

1. Coloque Word, Markdown, texto, PDF ou JSON em `docs/apresentacao/conhecimento/`.
2. Dê dois cliques em `docs/apresentacao/gerar-conhecimento.bat`.

Mais em [`docs/apresentacao/COMO-ALIMENTAR-A-BASE.md`](docs/apresentacao/COMO-ALIMENTAR-A-BASE.md). Os documentos de exemplo são fictícios.

## Problema

O analista de risco de fornecedores precisa identificar a empresa, juntar informações de telas separadas e
provar de onde tirou cada número. Uma resposta de IA sem fonte não serve para compliance.

**Hipótese, ainda não validada:** o levantamento leva mais de 30 minutos por fornecedor e pode cair para
minutos, com fonte conferível. Saberemos que é verdade se 3 especialistas confirmarem.

## Escopo do MVP

**Obrigatório**
- Captura de portal com hash e proveniência
- Normalização de contrato, licitação e fornecedor
- Dois tenants e dois perfis de acesso
- Pergunta em linguagem natural e resposta com âncora conferível
- Registro de consultas e fontes

**Diferenciais**
- Bloqueio entre perfis demonstrado ao vivo
- Três ataques de prompt barrados
- Pessoa física guardada só por hash
- IA declara o que não foi coletado

**Fora do MVP:** captura real de vários estados (o isolamento entre estados é provado com um segundo estado fictício),
score de risco, leitura dos PDFs anexos e integração com produtos da Bernhoeft.

## Arquitetura

```text
Site ── fila ──> Worker no notebook ────┐
WhatsApp ──> Gateway ──> Sessão ────────┴─> Agente ─> Consultas com perfil ─> Neo4j <─ Extração <─ Portais
```

- **Prova:** fato sem âncora não entra no modelo. A resposta abre o trecho literal.
- **Acesso:** o filtro roda antes da LLM. Dado não autorizado nunca chega a ela.
- **Segurança:** o agente não escreve consultas, e o texto do portal é tratado como dado, nunca como instrução.
  São *guardrails* de camada de dados, e não filtros de palavras: o perfil vem do ambiente do servidor, as consultas são fixas e
  parametrizadas, os argumentos são validados e limitados, e cada consulta é registrada. Por isso um prompt malicioso, mesmo que
  convença o modelo, não consegue pedir o que o perfil não permite. Detalhes no [catálogo](docs/seguranca/ataques-de-prompt.md).

## Ontologia v1

`Ente` → `UnidadeJurisdicionada`, `ProcessoLicitatorio` → `Participacao`, `Contrato` → `Aditivo`,
`Fornecedor` (PJ ou PF) e `Obra` → `Medicao`. `Despesa` ainda depende de confirmar a ligação entre
pagamento e contrato.

Regras tiradas da captura real:

| Achado | Regra |
|---|---|
| Número de contrato se repete | Identidade pelo id interno do portal |
| Documento vem mascarado | Ligar pelo CNPJ completo |
| Mesma empresa com grafias diferentes | Nome não é identidade |
| Estimado, adjudicado e contratado divergem | Campos distintos, sem somar |
| Lista de fiscais publica CPF completo | Pessoa física guardada só por hash |

## Premissas, limitações e riscos

- O desafio pede portal **estadual**. A base foca o Estado de Pernambuco: 2.047 contratos de 2024 estruturados, 25.947 medidos de 2019 a 2024, e uma amostra de 100 contratos no grafo (70 do Estado, 30 de Garanhuns).
- Contratos do Estado desde 2025 estão no PE Integrado, protegido por reCAPTCHA. Não contornamos.
- A execução financeira é agregada por fornecedor, órgão e ano, só para os CNPJs da amostra. Não diz quanto foi pago de um contrato.
- Dado público não é automaticamente livre de LGPD. Dados brutos não são versionados.
- A coleta respeita `robots.txt`, não forja identidade e não contorna bloqueios.
- A tese de valor segue como hipótese até a validação com especialistas.
- "Controle de acesso por estado" pode significar estados diferentes, e não município mais Estado. Por segurança, o isolamento
  foi provado também com um segundo estado fictício (`ex-estado`). Vale confirmar com o mentor.

## Pendências conhecidas

O que **não** está resolvido, para ninguém se surpreender na hora da demonstração:

1. **Worker no notebook.** `chat/worker.py` atende o site e o WhatsApp com um agente isolado por pergunta. Não rode junto da sessão de
   canal do WhatsApp: as duas responderiam. Sem o notebook ligado, o site mostra erro e o bot não responde.
2. **Ataques com o modelo real.** Nenhum foi executado. A camada de dados está testada, mas a resposta do modelo não. Roteiro em
   [`docs/seguranca/ataques-de-prompt.md`](docs/seguranca/ataques-de-prompt.md#roteiro-de-teste-com-o-agente-real).
3. **WhatsApp sem isolamento.** A sessão roda dentro do projeto, com ferramentas além das do `transparencia` (AP-07), e o plano
   de perfil por número tem corrida entre remetentes simultâneos (AP-18). Para a demonstração: um número por perfil, um de cada vez.
4. **Portal estadual.** Painel de contratos de 2024 e execução da amostra coletados. Licitações do Estado têm só o número do processo, sem modalidade nem valores.
5. **Pagamento individual.** A consulta de ordens bancárias devolveu 0 linhas, e a ligação com o contrato segue sem confirmação (L03).
6. **Site em PHP: deploy e dispositivos reais.** As falhas que existiam no modelo antigo foram corrigidas (rota `PATCH` sem
   permissão removida; CSRF; limite de tentativas de login; login em tempo constante; `deploy.sh` com valores escapados). Falta
   publicar na Hostinger e testar lá, e testar em celular de verdade. Também faltam a página "Sobre nós" (A13, sem fotos nem textos) e
   o cabeçalho comum no chat (A10).

## Documentos

- [Spec do site e do chat](docs/specs/001-site-e-chat/spec.md)
- [Plano técnico do site e da API](docs/specs/001-site-e-chat/plan.md)
- [Tasks](docs/specs/001-site-e-chat/tasks.md)
- [Como rodar o site localmente](site/dev/README.md)
- [Backlog](docs/BACKLOG.md)
- [Catálogo de ataques de prompt e proteções](docs/seguranca/ataques-de-prompt.md)
- [Resultados dos testes de segurança](docs/testes-seguranca.md)
- [Como alimentar a base de conhecimento da demonstração](docs/apresentacao/COMO-ALIMENTAR-A-BASE.md)
- [Apresentação do Checkpoint 1](docs/apresentacao/checkpoint-1.html): baixe o arquivo e abra no navegador.
