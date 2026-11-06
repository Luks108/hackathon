# Plano técnico: site e chat

Implementa a [spec 001](spec.md).

## Stack

| Camada | Tecnologia | Onde roda |
|---|---|---|
| Páginas | HTML, CSS e JavaScript puros, sem build | Hostinger |
| API e login | PHP 8.2 e sessão PHP | Hostinger |
| Banco do site | MySQL | Hostinger |
| Worker do chat | Python 3.12 | Notebook, serviço `systemd --user` |
| Agente | `claude -p` com MCP `transparencia` | Notebook |
| Fatos e grafo | JSONL com evidência e Neo4j 5.26 | Notebook |
| WhatsApp | Bun, Baileys e sessão Claude aberta | Notebook |

## Arquitetura

```text
Navegador ──> API PHP + MySQL (Hostinger)
                 ▲
                 │ HTTPS, só de saída
Notebook ── Worker ──> claude -p ──> MCP transparencia ──> Neo4j

WhatsApp <── Gateway Baileys ──> Sessão aberta ──> MCP transparencia
                 ▲
                 └── Worker sincroniza os telefones aprovados
```

O notebook repete o que o gateway já faz: sai para buscar trabalho e devolve o resultado. A fila no MySQL faz o papel de `inbound.jsonl` e `outbox/`.

## Fluxo de uma pergunta

1. O navegador envia `POST /api/perguntas`.
2. O PHP confere sessão, plano e limites, e grava a pergunta com os entes do plano.
3. O worker pega a pergunta mais antiga.
4. O worker gera uma configuração MCP com esses entes e inicia o agente.
5. O worker envia lotes de eventos a cada 300 ms.
6. O navegador lê os eventos novos a cada 700 ms, até receber `fim` ou `erro`.

## Banco de dados

```sql
planos(id, nome, preco_mensal, franquia, preco_excedente, tenants JSON)

assinaturas(id, usuario_id, plano_id, status ENUM('ativa','cancelada'), criada_em)

telefones(id, usuario_id, numero UNIQUE,
          status ENUM('pendente','aprovado','revogado'),
          aprovado_por NULL, criado_em, atualizado_em)

perguntas(id, usuario_id, plano_id, texto, tenants JSON,
          status ENUM('fila','processando','concluida','erro'),
          criada_em, iniciada_em, concluida_em, duracao_ms)

eventos(id, pergunta_id, seq,
        tipo ENUM('consulta','texto','fonte','fim','erro'),
        dados JSON, criado_em, UNIQUE(pergunta_id, seq))

tentativas_login(email, ip, criada_em)
```

### Planos de demonstração

Valores são hipótese, não preço validado.

| Plano | Mensal | Franquia | Excedente | Entes |
|---|---|---|---|---|
| Município | R$ 990 | 300 | R$ 1,50 | `pe-garanhuns` |
| Estado | R$ 1.990 | 1.000 | R$ 1,50 | `pe-estado`, `pe-garanhuns` |

## Contrato da API

Respostas em JSON. Erros usam `{ "erro": "mensagem legível" }`.

### Navegador

Rotas de escrita exigem o cabeçalho `X-CSRF-Token`.

| Método | Rota | Uso |
|---|---|---|
| POST | `/api/cadastro` | `{nome, email, senha}` cria a conta |
| POST | `/api/login`, `/api/logout` | Entrar e sair |
| GET | `/api/me` | Usuário, plano e token CSRF |
| GET | `/api/planos` | Lista pública |
| POST | `/api/assinatura` | `{plano_id}` ativa o plano de demonstração |
| GET, POST | `/api/telefones` | Listar e cadastrar `{numero}` |
| DELETE | `/api/telefones/{id}` | Remover |
| POST | `/api/perguntas` | `{texto}` devolve `{id}` |
| GET | `/api/perguntas/{id}/eventos?desde=0` | Só o dono lê; devolve eventos e `status` |

### Administrador

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/admin/telefones?status=pendente` | Fila de aprovação |
| POST | `/api/admin/telefones/{id}/aprovar` | Aprova |
| POST | `/api/admin/telefones/{id}/revogar` | Revoga |

### Worker

Todas exigem `X-Worker-Key`, com a chave em `WORKER_KEY`.

| Método | Rota | Uso |
|---|---|---|
| POST | `/api/worker/proxima` | Reserva uma pergunta ou devolve `204` |
| POST | `/api/worker/perguntas/{id}/eventos` | Grava `{eventos:[{seq,tipo,dados}]}`, sem duplicar `seq` |
| GET | `/api/worker/telefones` | Números aprovados e entes do plano |

### Eventos

```json
{ "seq": 1, "tipo": "consulta", "dados": { "nome": "sancoes_do_fornecedor" } }
{ "seq": 2, "tipo": "texto", "dados": { "delta": "Encontrei " } }
{ "seq": 3, "tipo": "fonte", "dados": { "evidencia": "...", "trecho": "...", "url": "...", "capturado_em": "2026-11-05" } }
{ "seq": 4, "tipo": "fim", "dados": { "duracao_ms": 18200 } }
{ "seq": 5, "tipo": "erro", "dados": { "motivo": "A consulta demorou mais que o esperado." } }
```

## Agente

O worker roda, por pergunta, em um diretório neutro:

```bash
claude -p "<pergunta>" \
  --model <modelo> \
  --mcp-config <configuração gerada> \
  --strict-mcp-config \
  --setting-sources "" \
  --system-prompt "<regras>" \
  --allowedTools "mcp__transparencia__..." \
  --output-format stream-json \
  --include-partial-messages \
  --verbose
```

A configuração gerada define `TRANSPARENCIA_TENANTS` e `TRANSPARENCIA_VER_PESSOAL=nao`. A pergunta é tratada como dado do usuário.

## WhatsApp

- O worker consulta `/api/worker/telefones` a cada 15 s.
- Número novo entra em `access.json`; número revogado sai. O dono nunca sai.
- O worker grava `perfis.json` com número e entes.
- Para RF-21, o `canal.ts` grava o perfil do remetente antes de entregar a mensagem, e o MCP lê esse arquivo. A sessão continua única: com pessoas perguntando ao mesmo tempo, há risco de troca de perfil. Limitação aceita só na POC.

## Segurança

- `WORKER_KEY` fica no `hackathon-config.php` e no `.env` do notebook.
- Texto de pergunta é escapado na tela com `textContent`.
- O PHP usa consultas preparadas.
- Pergunta presa em `processando` por mais de 180 s vira `erro`.
- Portal e pergunta nunca alteram plano, entes ou acesso.

## Riscos

| Risco | Resposta |
|---|---|
| Notebook desliga, dorme ou perde a rede | Tomada, sem suspensão e 4G de reserva; o site mostra "serviço indisponível" |
| Bloqueio do Baileys | Chat do site vira plano B da demo |
| Muitas requisições na Hostinger | Atualizar só com pergunta aberta |
| Avaliador pede WebSocket | Explicar a troca; no corporativo, o servidor de chat em VPS permite WebSocket |
| Disco do notebook | Sem novas imagens; manter folga de pelo menos 3 GB |
