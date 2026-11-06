# Tasks: site e chat

Baseadas na [spec](spec.md) e no [plano técnico](plan.md). Se a tarefa mudar o contrato, atualize o plano no mesmo pull request.

**Dev A:** site e conta, em PHP · **Dev B:** worker, agente e WhatsApp, em Python

## Comece aqui

- [ ] **T00.** Dev A e Dev B leem spec e plano, e confirmam o contrato. 20 min.
- [ ] **T01.** Dono gera `WORKER_KEY` e coloca no `.env` e no `deploy.sh`. Depende de T00.

## Dev A: site e conta

### Base

- [ ] **A01.** Criar as tabelas e os planos no `setup.php`. *Aceite:* banco limpo recebe tudo; repetir não duplica.
- [ ] **A02.** Criar `POST /api/cadastro`. RF-05. *Aceite:* conta criada entra; e-mail repetido recebe erro.
- [ ] **A03.** Proteger login e escrita. RF-06, RNF-06. *Aceite:* CSRF ausente recebe 403; tentativas seguidas são limitadas.
- [ ] **A04.** Criar planos e assinatura. RF-07, RF-08. *Aceite:* ativa sem pagamento; `/api/me` mostra o plano.

### Fila

- [ ] **A05.** Criar `POST /api/perguntas`. RF-08, RF-13. *Aceite:* copia os entes do plano; segunda pergunta aberta recebe 409; mais de 500 caracteres recebe 400.
- [ ] **A06.** Criar leitura de eventos. RF-09. *Aceite:* devolve só `seq` maior que `desde`; outro usuário recebe 404.
- [ ] **A07.** Criar rotas do worker. *Aceite:* sem chave recebe 401; dois pedidos não pegam a mesma pergunta; `seq` repetido é ignorado.

### Telefones

- [ ] **A08.** Criar rotas de telefone do usuário. RF-17. *Aceite:* normaliza o número e não aceita duplicado.
- [ ] **A09.** Criar aprovação do administrador. RF-18. *Aceite:* usuário comum recebe 403; aprovação fica registrada.

### Telas

- [ ] **A10.** Criar layout comum e landing. RF-01, RNF-08. *Aceite:* funciona com 400 px e no teclado.
- [ ] **A11.** Criar planos. RF-02. *Aceite:* lê `/api/planos` e mostra o aviso de demonstração.
- [ ] **A12.** Criar modelo de negócios. RF-04. *Aceite:* marca os valores como hipótese.
- [ ] **A13.** Criar sobre nós. RF-03. *Depende de:* fotos, textos e autorização do time.
- [ ] **A14.** Criar login, cadastro e conta. RF-05 a RF-08, RF-17. *Aceite:* conta mostra plano e estado do telefone.
- [ ] **A15.** Criar chatbox. RF-09, RF-10, RF-14. *Aceite:* mostra consulta, texto parcial, fontes e erro; para de consultar ao terminar.
- [ ] **A16.** Criar tela do administrador. RF-18. *Aceite:* aprova e revoga em um clique.

## Dev B: worker, agente e WhatsApp

### Agente

- [ ] **B01.** Criar `chat/agente.py` a partir do exemplo do Polis. RNF-03, RNF-04. *Aceite:* roda em diretório neutro e só chama tools do `transparencia`.
- [ ] **B02.** Traduzir o `stream-json` para eventos. RF-09, RF-10. *Aceite:* gera `consulta`, `texto`, `fonte` e `fim`.
- [ ] **B03.** Criar regras do agente. RF-11, RF-12. *Aceite:* cita evidência; sem dado, chama `cobertura` antes de negar.
- [ ] **B04.** Fazer `conferir_evidencia` chegar à resposta. RF-10. *Aceite:* cada fato traz trecho, data e link.

### Worker

- [ ] **B05.** Criar `chat/worker.py`. RF-14, RF-15, RNF-02. *Aceite:* pega a pergunta, envia lotes e encerra em até 120 s.
- [ ] **B06.** Testar com API falsa. *Aceite:* funciona antes de A07 ficar pronta.
- [ ] **B07.** Medir o tempo. RNF-01. *Aceite:* registra primeiro sinal e duração total.

### WhatsApp

- [ ] **B08.** Sincronizar telefones. RF-19, RF-20. *Aceite:* aprovar libera e revogar corta em até 30 s; o dono nunca sai.
- [ ] **B09.** Atualizar `CLAUDE.md` e o texto do `canal.ts` sobre acesso. RF-20. *Aceite:* continua proibido liberar por mensagem.
- [ ] **B10.** Aplicar perfil por número. RF-21. *Aceite:* dois números veem resultados diferentes.

### Operação e testes

- [ ] **B11.** Criar serviço do worker e ativar o `wa-gateway` no login. RNF-09. *Aceite:* reiniciar o notebook não exige comando manual.
- [ ] **B12.** Validar base e fontes. *Aceite:* perguntas do roteiro batem com a evidência.
- [ ] **B13.** Rodar testes de perfil e injeção. *Aceite:* resultados registrados em `docs/testes-seguranca.md`.

## Integração

- [ ] **I01.** Deploy na Hostinger com `./site/deploy.sh --setup`. Depende de A01 a A07.
- [ ] **I02.** Pergunta real do chat, de ponta a ponta. Depende de A15, B05 e I01.
- [ ] **I03.** Telefone aprovado fala no WhatsApp. Depende de A16 e B08.
- [ ] **I04.** Roteiro completo com duas contas. Depende de I02, I03 e B10.
- [ ] **I05.** README, limitações, ajuste dos slides e ensaio. Depende de I04.

## Paralelismo

```text
T00 ─┬─ A01 → A02 → A03 → A04 → A05 → A06 → A07 ─┐
     │  A10 → A11 → A12 → A13 → A14 → A15 → A16 ─┤
     └─ B01 → B02 → B03 → B04 → B05 → B06 ───────┴─> I01 → I02 → I03 → I04 → I05
```

## Cronograma

| Quando | Dev A | Dev B | Marco |
|---|---|---|---|
| Hoje à noite | A01 a A07 | B01 a B06 | Fila e agente prontos |
| 06/11, até 9h40 | A08 a A15 | B07 a B09 | **I02:** chat real |
| 06/11, até 11h | A16 | B10 a B13 | **I03 e I04:** demo completa |
| 06/11, até 12h | I05 | I05 | Code freeze |

## Ordem de corte

1. RF-16, histórico ao recarregar.
2. A12 vira uma seção da landing.
3. A16 vira comando no banco para aprovar.
4. B10: o bloqueio entre planos fica demonstrado só no site.

**Não sai:** login, fila, resposta parcial, fonte, bloqueio entre planos e WhatsApp.
