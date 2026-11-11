# Spec 001: site e chat

**Status:** pronta para desenvolvimento · **Code freeze:** 06/11/2026, 12h

## Objetivo

Dar ao produto uma porta de entrada. O site apresenta a oferta, cria a conta e libera o telefone. O WhatsApp segue como estrela da demo, porque foi o que impressionou o patrocinador.

## Fluxo da demo

1. A visitante conhece o produto e os planos.
2. Cria a conta e ativa um plano de demonstração.
3. Pergunta sobre um fornecedor no chat e vê a resposta aparecer com a fonte.
4. Cadastra o telefone, e o administrador aprova.
5. Faz a pergunta no WhatsApp.
6. Uma conta com plano menor faz a mesma pergunta e não vê os dados do Estado.

## Histórias e requisitos

### H1. Conhecer o produto

| ID | Requisito | Prioridade |
|---|---|---|
| RF-01 | A landing mostra proposta de valor, como funciona, chamada para ação e aviso de que a base é uma amostra | Deve |
| RF-02 | A página de planos mostra preço, entes cobertos e o aviso "valores de demonstração" (franquia e excedente aparecem só se o plano os tiver) | Deve |
| RF-03 | Sobre nós mostra foto, nome, papel e descrição de cada pessoa do time | Deve |
| RF-04 | O modelo de negócios mostra proposta de valor, quem paga e como o preço funciona, com hipóteses marcadas | Deve |

### H2. Criar conta e ativar plano

| ID | Requisito | Prioridade |
|---|---|---|
| RF-05 | A pessoa cria conta com nome, e-mail e senha | Deve |
| RF-06 | A pessoa entra e sai; senha errada mostra erro sem dizer qual campo falhou | Deve |
| RF-07 | Ativar um plano não pede pagamento nem dado de cartão | Deve |
| RF-08 | O chat e o telefone exigem sessão e plano ativo | Deve |

### H3. Perguntar no site

| ID | Requisito | Prioridade |
|---|---|---|
| RF-09 | A pessoa envia uma pergunta e vê o andamento, as consultas e o texto parcial sem recarregar | Deve |
| RF-10 | A resposta mostra as fontes e permite abrir o trecho da evidência | Deve |
| RF-11 | A resposta respeita os entes do plano; dado fora do plano não é consultado | Deve |
| RF-12 | Registros de pessoa física não aparecem | Deve |
| RF-13 | Cada conta tem uma pergunta aberta por vez, com até 500 caracteres | Deve |
| RF-14 | Falha ou demora acima de 120 segundos gera mensagem legível | Deve |
| RF-15 | O sistema registra usuário, plano, pergunta, consultas, evidências e tempo | Deve |
| RF-16 | A conversa continua visível ao recarregar a página | Poderia |

### H4. Liberar o telefone

| ID | Requisito | Prioridade |
|---|---|---|
| RF-17 | A pessoa cadastra e remove o telefone na conta | Deve |
| RF-18 | O telefone começa pendente e só o administrador aprova ou revoga | Deve |
| RF-19 | Número aprovado passa a falar com o bot; número revogado deixa de falar | Deve |
| RF-20 | Pedido feito por mensagem no WhatsApp nunca muda acesso | Deve |
| RF-21 | No WhatsApp, a resposta respeita o plano do número | Deveria |

## Requisitos não funcionais

| ID | Requisito | Medida |
|---|---|---|
| RNF-01 | Tempo real | Primeiro sinal na tela em até 3 s depois de o notebook pegar a pergunta; texto atualizado a cada 1 s ou menos |
| RNF-02 | Notebook sem porta aberta | Só conexões de saída; nenhum túnel ou serviço público |
| RNF-03 | Perfil fora do alcance do modelo | Os entes vêm do banco e entram no ambiente do servidor MCP |
| RNF-04 | Agente isolado | Diretório neutro, sem `CLAUDE.md`, só com as tools do `transparencia` |
| RNF-05 | Segredos | Fora do repositório e do JavaScript do navegador |
| RNF-06 | Login | Senha com hash, cookie HttpOnly e Secure, CSRF e limite de tentativas |
| RNF-07 | Hospedagem | Sem processo longo na Hostinger; requisições curtas |
| RNF-08 | Acessibilidade | Funciona no celular e no teclado |
| RNF-09 | Volta após falha | O notebook retoma sozinho o gateway e o worker após reiniciar |

## Fora do escopo

- Stripe, cartão ou cobrança real.
- WebSocket no navegador.
- API oficial do WhatsApp e VPS.
- Postgres no MVP. A extração e o Neo4j atendem a demo.
- Recuperação de senha, verificação de e-mail e histórico entre sessões.
- Coleta completa do portal do Estado.

## Decisões

| Decisão | Motivo |
|---|---|
| Site na Hostinger | Já está no ar, com PHP 8.2 e MySQL |
| Fila em vez de WebSocket | Repete o desenho do WhatsApp: o notebook só faz conexões de saída, sem túnel. O pedido original era WebSocket; a troca atende "tempo real" sem complexidade extra |
| Atualização a cada 0,7 s | Hospedagem compartilhada não aceita WebSocket de entrada, e conexão longa ocuparia processo |
| Administrador aprova telefone | Mantém uma pessoa no controle do acesso |
| Duas frentes | Time de duas pessoas, com o contrato no [plano técnico](plan.md) |

## Critérios de aceite da entrega

- [ ] Fluxo da demo completo, em uma conta nova.
- [ ] Mesma pergunta com dois planos gera respostas diferentes, e o log comprova.
- [ ] Três ataques de prompt não mudam entes nem expõem pessoa física.
- [ ] Notebook reiniciado volta a responder sem intervenção.
- [ ] Nenhum segredo ou dado pessoal no repositório.
- [ ] README com instruções de execução, premissas e limitações.
