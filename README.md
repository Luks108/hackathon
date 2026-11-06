# Histórico de fornecedor com prova

Projeto do **Desafio 1 — Portal Inteligente de Transparência com IA** do Hack Garanhuns Tech 2026.

Consulta em linguagem natural a dados públicos de contratação. Toda resposta aponta para o trecho literal
da fonte, e cada perfil vê só o que está autorizado a ver.

> **Estado:** extração, grafo, consultas com filtro de perfil, registro de consultas e catálogo de ataques estão prontos e
> **testados** (43 testes automáticos). Ainda falta o agente isolado (worker) ligado ao site e os ataques rodados com o
> modelo real. Veja [Onde estamos no desafio](#onde-estamos-no-desafio) e [Pendências conhecidas](#pendências-conhecidas).
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
| `site/` | Site PHP + MySQL na Hostinger (ainda é o modelo de registros com foto) |
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
.venv/bin/python coleta/amostra.py
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

- O desafio pede portal **estadual**. Até agora capturamos o municipal de Garanhuns; o portal de PE ainda será avaliado.
- A captura cobre contratos, licitações, diárias, obras e legislação. Pagamentos a fornecedores ainda não foram coletados.
- Dado público não é automaticamente livre de LGPD. Dados brutos não são versionados.
- A coleta respeita `robots.txt`, não forja identidade e não contorna bloqueios.
- A tese de valor segue como hipótese até a validação com especialistas.
- "Controle de acesso por estado" pode significar estados diferentes, e não município mais Estado. Por segurança, o isolamento
  foi provado também com um segundo estado fictício (`ex-estado`). Vale confirmar com o mentor.

## Pendências conhecidas

O que **não** está resolvido, para ninguém se surpreender na hora da demonstração:

1. **Agente isolado (worker).** O chat do site ainda não conversa com o agente real (tasks B01 a B07). A página de
   demonstração é simulada.
2. **Ataques com o modelo real.** Nenhum foi executado. A camada de dados está testada, mas a resposta do modelo não. Roteiro em
   [`docs/seguranca/ataques-de-prompt.md`](docs/seguranca/ataques-de-prompt.md#roteiro-de-teste-com-o-agente-real).
3. **WhatsApp sem isolamento.** A sessão roda dentro do projeto, com ferramentas além das do `transparencia` (AP-07), e o plano
   de perfil por número tem corrida entre remetentes simultâneos (AP-18). Para a demonstração: um número por perfil, um de cada vez.
4. **Portal estadual.** Só o CSV de sanções de PE entrou. A coleta dos painéis do Estado não foi testada (L02).
5. **Pagamentos** não foram coletados, e a ligação com o contrato não foi confirmada (L03).
6. **Site em PHP** (`site/`). Ainda é o modelo de registros com foto. Falhas conhecidas para quem reescrever a API (Dev A):
   - `PATCH /api/registros/{id}` aceita qualquer usuário logado, sem checar permissão;
   - não há proteção CSRF nem limite de tentativas de login;
   - o login responde mais rápido quando o e-mail não existe (revela quais e-mails têm conta);
   - `site/deploy.sh` grava segredos entre aspas simples sem escapar, então uma senha com `'` quebra o arquivo de configuração.
   Não foram alteradas aqui para não conflitar com a reescrita da API.

## Documentos

- [Spec do site e do chat](docs/specs/001-site-e-chat/spec.md)
- [Backlog](docs/BACKLOG.md)
- [Catálogo de ataques de prompt e proteções](docs/seguranca/ataques-de-prompt.md)
- [Resultados dos testes de segurança](docs/testes-seguranca.md)
- [Como alimentar a base de conhecimento da demonstração](docs/apresentacao/COMO-ALIMENTAR-A-BASE.md)
- [Apresentação do Checkpoint 1](docs/apresentacao/checkpoint-1.html): baixe o arquivo e abra no navegador.
