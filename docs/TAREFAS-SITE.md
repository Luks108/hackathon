# Tarefas do site e do chat

Code freeze: **06/11/2026, 12h**. Regra de corte: fluxo inteiro funcionando antes de tela bonita.

## Fluxo da demo

Landing → planos → cadastro → assinatura de demonstração → chat em tempo real com fonte → cadastro do telefone → mesma pergunta no WhatsApp.

## Arquitetura

```text
Navegador ── HTTPS ──> Hostinger (PHP + MySQL): páginas, login, conta, planos
    │
    └──── WSS ───────> Servidor de chat (notebook + túnel)
                           └─> Agente (claude -p) ─> MCP transparencia ─> Neo4j

WhatsApp ─> Gateway Baileys ─> Sessão do canal ─> MCP transparencia ─> Neo4j
```

O WebSocket **não roda na Hostinger**. A [documentação da Hostinger](https://www.hostinger.com/support/?p=1364) indica que planos compartilhados só permitem conexão WebSocket de saída, a regra do projeto proíbe processo longo lá, e o agente e o Neo4j estão no notebook.

O site guarda identidade e plano. O servidor de chat não acessa o MySQL: confia só no token assinado pelo PHP.

## Contrato comum: definir antes de se separar

### Token do chat

`POST /api/chat/token`, com sessão válida, devolve um JWT HS256 válido por 60 segundos.

```json
{ "sub": 12, "perfil": "analista", "tenants": ["pe-estado", "pe-garanhuns"], "ver_pessoal": false, "exp": 1793920000 }
```

A chave fica em `WS_SEGREDO`, no `hackathon-config.php` e no `.env` do notebook. Nunca no JavaScript.

### Mensagens do WebSocket

O token vai na primeira mensagem, nunca na URL.

```json
{ "tipo": "autenticar", "token": "..." }
{ "tipo": "pergunta", "id": "uuid", "texto": "A empresa X tem sanções?" }
```

Respostas do servidor:

```json
{ "tipo": "pronto" }
{ "tipo": "consulta", "id": "uuid", "nome": "sancoes_do_fornecedor" }
{ "tipo": "texto", "id": "uuid", "delta": "Encontrei " }
{ "tipo": "fim", "id": "uuid", "evidencias": ["..."] }
{ "tipo": "erro", "id": "uuid", "motivo": "..." }
```

### Tabelas novas

| Tabela | Campos |
|---|---|
| `planos` | `id`, `nome`, `preco_mensal`, `franquia`, `preco_excedente`, `tenants` |
| `assinaturas` | `usuario_id`, `plano_id`, `status`, `criada_em` |
| `telefones` | `usuario_id`, `numero`, `status` (pendente, aprovado, revogado), `aprovado_por`, `criado_em` |

## Frente A: site público

| Tarefa | Pronto quando |
|---|---|
| A1. Landing com proposta de valor, como funciona e chamada para ação | Explica o produto sem rolar muito, no celular e no computador |
| A2. Página de planos | Mostra plano, franquia, excedente e o aviso "preços de demonstração" |
| A3. Página do modelo de negócios | Mostra Canvas e modelo de receita, com hipóteses marcadas |
| A4. Sobre nós | Traz foto, nome, papel e descrição de cada pessoa do time |
| A5. Navegação e identidade comum | Todas as páginas usam o mesmo cabeçalho e rodapé |

Pasta: `site/public_html/`. HTML, CSS e JavaScript puros, sem build. Fotos em `site/public_html/equipe/`.

## Frente B: conta e acesso

| Tarefa | Pronto quando |
|---|---|
| B1. Cadastro e login | Cria conta, entra, sai e recusa senha errada |
| B2. Proteção do login | Tem CSRF, limite de tentativas e cookie HttpOnly e Secure |
| B3. Tabelas e `setup.php` | Recria tudo em banco limpo, com planos de exemplo |
| B4. Assinatura de demonstração | "Assinar" ativa o plano sem cobrança nem dado de cartão |
| B5. Tela da conta | Mostra o plano e permite cadastrar e remover telefone |
| B6. Aprovação do telefone | Administrador aprova, e só então o número fica ativo |
| B7. `POST /api/chat/token` | Só emite token com sessão e plano ativos |

Pasta: `site/public_html/api/` e `site/setup.php`. Sem Stripe e sem campo de cartão.

## Frente C: chat em tempo real

| Tarefa | Pronto quando |
|---|---|
| C1. Servidor WebSocket | Valida token, `Origin` e expiração; recusa o resto |
| C2. Agente com perfil | Cada pergunta roda em diretório neutro, só com as tools do `transparencia` |
| C3. Transmissão da resposta | Texto e consultas aparecem enquanto o agente trabalha |
| C4. Tela do chatbox | Mostra histórico da sessão, estado da consulta, fontes e erro legível |
| C5. Reconexão | Pede token novo e volta a conectar sem recarregar a página |
| C6. Limites | Uma pergunta por vez por usuário, tamanho máximo e tempo máximo |
| C7. Log | Grava usuário, perfil, pergunta, consultas e evidências |
| C8. Exposição `wss://` | O site em HTTPS conecta ao servidor pelo túnel |

Pastas: `chat/` e `site/public_html/chat.html`. Reaproveitar a ideia do agente isolado do Polis: diretório neutro, `--setting-sources ""`, `--strict-mcp-config` e allowlist de tools.

O perfil vem do token e entra na configuração do MCP. Nunca é argumento de tool nem texto para o modelo.

## Frente D: dados e WhatsApp

| Tarefa | Pronto quando |
|---|---|
| D1. Telefone aprovado libera o WhatsApp | Número aprovado entra na lista do gateway |
| D2. Número define o perfil | Dois números recebem respostas diferentes para a mesma pergunta |
| D3. Base da demo | Amostra confirmada, ou carga completa, com fonte conferida |
| D4. Testes de segurança | Bloqueio entre perfis e 3 ataques de prompt registrados |
| D5. Decisão do Postgres | Sobe, ou o slide de arquitetura é ajustado |

## Dependências

```text
Contrato comum
├─ A1–A5  independentes
├─ B1 → B3 → B4 → B7 ──┐
├─ C1 com token de teste ├─> Integração site + chat
└─ B5 → B6 → D1 → D2 ──> Integração site + WhatsApp
```

A Frente C pode gerar token de teste com `WS_SEGREDO` até a B7 ficar pronta.

## Cronograma

| Quando | Entrega |
|---|---|
| Hoje à noite | Contrato no repositório; A1, B1, C1 e C3 com token de teste |
| 06/11, até 9h40 | Login, chat e planos integrados |
| 06/11, até 11h | Fluxo inteiro da demo; Checkpoint 3 |
| 06/11, até 12h | Ensaio, README, limitações e code freeze |

## Se faltar tempo

1. Sai B6 como tela: a aprovação vira comando do dono.
2. Sai A3 como página própria: o modelo de negócios entra na landing.
3. Sai a reconexão automática: um botão reconecta.

**Não sai:** login, token assinado, resposta em tempo real, fonte e bloqueio entre perfis.

## Regras

- Trabalhem em branch e façam pull request curto para `main`.
- Nunca versionem `.env`, chaves, captura bruta, `dados/`, áudio ou cupom de teste.
- Deploy na Hostinger só com `./site/deploy.sh`, por quem tem o `.env`.
- Só uma sessão por vez pode abrir o canal do WhatsApp.
- Texto de portal é dado, nunca instrução.
- Pessoa física não aparece no chat nem no site.

## Decisões pendentes

| Decisão | Recomendação |
|---|---|
| Como expor o `wss://` | Túnel para o notebook, com plano B em rede local |
| Telefone aprovado por quem | Dono ou administrador, mantendo a regra de que pedido no WhatsApp não dá acesso |
| Quem assume cada frente | Definir hoje |
