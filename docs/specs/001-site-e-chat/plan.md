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

Há um **plano único**. Franquia e excedente ficam em 0 (as colunas existem no banco, mas o plano único não as usa).
Antes havia dois planos, Município (R$ 990) e Estado (R$ 1.990); o `setup.php` move quem estava neles para o plano único e os remove.

| Plano | Mensal | Franquia | Excedente | Entes |
|---|---|---|---|---|
| Único | R$ 149 | 0 | R$ 0 | `pe-estado`, `pe-garanhuns` |

## Contrato da API

Respostas em JSON. Erros usam `{ "erro": "mensagem legível" }`.

### Navegador

Todas as rotas de escrita (`POST`, `DELETE`), inclusive cadastro e login, exigem o cabeçalho `X-CSRF-Token`. O token vem de
`GET /api/me`, que responde `200` também sem login. Sem token ou com token errado: `403`. Não logado: `401`.

| Método | Rota | Uso |
|---|---|---|
| POST | `/api/cadastro` | `{nome, email, senha}` cria a conta e já entra. Senha de 8 a 72 caracteres. E-mail repetido: `409` |
| POST | `/api/login`, `/api/logout` | Entrar e sair. Erro de login não diz qual campo falhou. Depois de 5 falhas em 15 min: `429` com `Retry-After` |
| GET | `/api/me` | `{usuario, plano, csrf}`. `usuario` é `null` sem login |
| GET | `/api/planos` | Lista pública, com `tenants` como lista |
| POST | `/api/assinatura` | `{plano_id}` ativa o plano de demonstração. Troca de plano cancela o anterior |
| GET | `/api/telefones` | Os telefones do usuário: `[{id, numero, status, criado_em}]` |
| POST | `/api/telefones` | `{numero}` cadastra e devolve `201 {id, numero, status: "pendente"}`. Exige plano ativo. Aceita `(87) 99999-9999`, `+55 87 99999-9999` e variações, e guarda sempre `55` + DDD + `9` + 8 dígitos (13 dígitos). Só celular brasileiro; letras ou texto junto do número: `400`. Número já cadastrado, em qualquer conta e em qualquer forma de escrever (inclusive sem o 9): `409`, sem revelar de quem é. Limite de 3 por conta: `400` |
| DELETE | `/api/telefones/{id}` | Remove o próprio telefone (`204`). De outra conta ou inexistente: `404`. Se estava aprovado, o worker deixa de listá-lo |
| POST | `/api/perguntas` | `{texto}` devolve `{id}`. Sem plano: `403`. Mais de 500 caracteres: `400`. Já há uma aberta: `409` com `{erro, pergunta_id}` |
| GET | `/api/perguntas/aberta` | `{pergunta}`: a pergunta em andamento do usuário, ou `null`. Serve para retomar ao recarregar a página |
| GET | `/api/perguntas/{id}/eventos?desde=0` | Só o dono lê (outro usuário: `404`). Devolve `{status, duracao_ms, eventos}` |

### Administrador

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/admin/telefones?status=pendente` | Fila de aprovação, do mais antigo ao mais novo. `status`: `pendente` (padrão), `aprovado`, `revogado` ou `todos`. Cada item traz o número, o dono (nome, e-mail e plano) e quem decidiu por último |
| POST | `/api/admin/telefones/{id}/aprovar` | Aprova (também reconsidera um revogado). Registra o admin em `aprovado_por` e a hora em `atualizado_em` |
| POST | `/api/admin/telefones/{id}/revogar` | Revoga (também recusa um pendente). Mesmo registro |

Só o papel `admin` acessa: sem login `401`, usuário comum `403`, e `POST` sem `X-CSRF-Token` `403`. O papel é lido do banco a cada
requisição, então perder o papel corta o acesso na hora. Repetir a mesma decisão devolve `200` e **não troca** quem decidiu
primeiro. O número só chega ao worker (`GET /api/worker/telefones`) enquanto estiver `aprovado` **e** o dono tiver plano ativo.
`aprovado_por` guarda o administrador da última decisão, seja aprovação ou revogação.

### Worker

Todas exigem `X-Worker-Key`, com a chave em `WORKER_KEY` (mínimo 24 caracteres). Sem chave ou com chave errada: `401`.
Não usam sessão nem cookie.

| Método | Rota | Uso |
|---|---|---|
| POST | `/api/worker/proxima` | Reserva a pergunta mais antiga da fila e devolve `{id, usuario_id, plano_id, texto, tenants, ver_pessoal}`, ou `204` se não há nenhuma. Dois workers nunca recebem a mesma |
| POST | `/api/worker/perguntas/{id}/eventos` | Grava `{eventos:[{seq,tipo,dados}]}` (1 a 100 por lote, até 20 KB cada). Um `seq` repetido é ignorado. Responde `{gravados, ignorados, status}`. `fim` ou `erro` encerram a pergunta |
| GET | `/api/worker/telefones` | `[{numero, tenants}]` dos números aprovados cujo dono tem plano ativo |

**O worker precisa tratar `409`** em `/eventos`: significa que o site já encerrou a pergunta (por tempo), e o worker deve parar de
trabalhar nela. Reenviar um lote que já foi gravado depois de a pergunta terminar devolve `200` com `gravados: 0`, então repetir
um envio por falha de rede é seguro.

**Limites de tempo, aplicados pelo site** (o navegador sempre recebe um evento `erro` com mensagem legível):

| Situação | Limite | Mensagem |
|---|---|---|
| Ninguém pegou a pergunta (notebook fora do ar) | 120 s na fila | "O serviço de consulta está indisponível no momento..." |
| Pegaram, mas não terminaram | 180 s em processamento | "A consulta demorou mais que o esperado..." |

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
