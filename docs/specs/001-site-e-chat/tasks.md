# Tasks: site e chat

Baseadas na [spec](spec.md) e no [plano técnico](plan.md). Se a tarefa mudar o contrato, atualize o plano no mesmo pull request.

**Dev A:** site e conta, em PHP · **Dev B:** worker, agente e WhatsApp, em Python · **Lucas:** dados, ontologia, banco, revisão e deploy

## Como trabalhamos

- Dev A e Dev B desenvolvem na própria máquina, em branch, e abrem pull request para `main`.
- Ninguém além do Lucas acessa o notebook, a captura real, os segredos ou a Hostinger.
- O Lucas revisa, faz o merge, sobe na Hostinger com `./site/deploy.sh` e liga o worker no notebook.
- Dev B usa os dados fictícios de `fixtures/exemplo`: copie `.env.exemplo` para `.env` e rode `coleta/carregar_neo4j.py --zerar --exemplo`.
- Dev A testa o site com PHP e MySQL locais e uma `WORKER_KEY` própria.
- **Prévia: 06/11, 4h.** Abra o pull request com o que estiver pronto, mesmo incompleto.
- **Prazo de entrega ao Lucas: 06/11, 5h.** Depois disso, só correção.

## Comece aqui

- [ ] **T00.** Dev A e Dev B leem spec e plano, e confirmam o contrato. 20 min.
- [ ] **T01.** Lucas gera a `WORKER_KEY` de produção e coloca no `.env` e no `deploy.sh`. Depende de T00.

## Dev A: site e conta

### Base

- [x] **A01.** Criar as tabelas e os planos no `setup.php`. *Aceite:* banco limpo recebe tudo; repetir não duplica.
- [x] **A02.** Criar `POST /api/cadastro`. RF-05. *Aceite:* conta criada entra; e-mail repetido recebe erro.
- [x] **A03.** Proteger login e escrita. RF-06, RNF-06. *Aceite:* CSRF ausente recebe 403; tentativas seguidas são limitadas.
- [x] **A04.** Criar planos e assinatura. RF-07, RF-08. *(a escolha de plano na interface está desligada na demonstração: `ESCOLHER_PLANO` em `assets/chat.js`; a conta nova recebe o plano que cobre mais entes)* *Aceite:* ativa sem pagamento; `/api/me` mostra o plano.

### Fila

- [x] **A05.** Criar `POST /api/perguntas`. RF-08, RF-13. *Aceite:* copia os entes do plano; segunda pergunta aberta recebe 409; mais de 500 caracteres recebe 400.
- [x] **A06.** Criar leitura de eventos. RF-09. *Aceite:* devolve só `seq` maior que `desde`; outro usuário recebe 404.
- [x] **A07.** Criar rotas do worker. *Aceite:* sem chave recebe 401; dois pedidos não pegam a mesma pergunta; `seq` repetido é ignorado.

### Telefones

- [x] **A08.** Criar rotas de telefone do usuário. RF-17. *Aceite:* normaliza o número e não aceita duplicado.
- [x] **A09.** Criar aprovação do administrador. RF-18. *Aceite:* usuário comum recebe 403; aprovação fica registrada.

### Telas

- [ ] **A10.** Criar layout comum e landing. *(landing em `index.html` e topo comum nas páginas de conta e administração, em `assets/topo.js`; o chat ainda tem o próprio topo)* RF-01, RNF-08. *Aceite:* funciona com 400 px e no teclado.
- [ ] **A11.** Criar planos. RF-02. *Aceite:* lê `/api/planos` e mostra o aviso de demonstração.
- [ ] **A12.** Criar modelo de negócios. RF-04. *Aceite:* marca os valores como hipótese.
- [ ] **A13.** Criar sobre nós. RF-03. *Depende de:* fotos, textos e autorização do time.
- [x] **A14.** Criar login, cadastro e conta. RF-05 a RF-08, RF-17. *Aceite:* conta mostra plano e estado do telefone.
- [x] **A15.** Criar chatbox. RF-09, RF-10, RF-14. *Aceite:* mostra consulta, texto parcial, fontes e erro; para de consultar ao terminar.
- [x] **A16.** Criar tela do administrador. RF-18. *Aceite:* aprova e revoga em um clique.

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

- [ ] **B11.** Criar o arquivo de serviço do worker. RNF-09. *Aceite:* sobe com um comando; o Lucas ativa no notebook.
- [ ] **B13.** Rodar testes de perfil e injeção. *Aceite:* resultados registrados em `docs/testes-seguranca.md`.

## Lucas: dados, ontologia e banco

- [ ] **L01.** Definir a base da demo: amostra ou carga completa. *Aceite:* perguntas do roteiro têm resposta com evidência conferida.
- [ ] **L02.** Testar a coleta dos painéis de PE, com intervalo de 10 s. *Aceite:* volumes medidos e amostra com hash.
- [ ] **L03.** Confirmar a ligação entre pagamento e contrato. *Aceite:* regra escrita ou limitação registrada.
- [ ] **L04.** Evoluir a ontologia: `Empenho`, `Pagamento`, `Aditivo`, `Participacao`. *Aceite:* todo fato novo tem evidência.
- [ ] **L05.** Publicar novas consultas no MCP sem quebrar as atuais. *Aceite:* Dev B avisado de qualquer mudança no contrato.
- [ ] **L06.** Decidir o Postgres depois do MVP. *Aceite:* decisão registrada e slide coerente.
- [ ] **L07.** Ativar serviços no notebook. RNF-09. *Aceite:* reiniciar não exige comando manual.

## Integração

- [ ] **I01.** Lucas faz o deploy com `./site/deploy.sh --setup`. Depende de A01 a A07.
- [ ] **I02.** Lucas liga o worker, e o time testa uma pergunta real. Depende de A15, B05 e I01.
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
| 06/11, até 4h | A01 a A07 e A15 | B01 a B06 | **Prévia:** fila, agente e chatbox |
| 06/11, até 5h | A08 a A16 | B07 a B11 e B13 | **Entrega ao Lucas** |
| 06/11, até 11h | Correções | Correções | **I01 a I04:** deploy e demo completa |
| 06/11, até 12h | I05 | I05 | Code freeze |

## Ordem de corte

1. RF-16, histórico ao recarregar.
2. A12 vira uma seção da landing.
3. A16 vira comando no banco para aprovar.
4. B10: o bloqueio entre planos fica demonstrado só no site.

**Não sai:** login, fila, resposta parcial, fonte, bloqueio entre planos e WhatsApp.
