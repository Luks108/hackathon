# Backlog

Code freeze: **06/11/2026, 12h**. O que ficar de fora entra como próximo passo no registro de limitações.

**Critério de pronto:** uma pergunta real, resposta conferível, outro perfil bloqueado e tudo no log.

## Hoje, até o Checkpoint 1 (19h)
- [x] Capturar o portal de Garanhuns com hash
- [x] Criar o repositório
- [ ] Verificar se pagamento se liga a contrato
- [x] Ler os painéis do portal do Estado de PE; coleta ainda não testada

## Hoje, 19h50–21h30
- [x] Implementar a ontologia v1
- [x] Carregar amostra de 10 contratos no Neo4j
- [x] Criar as consultas com filtro de perfil
- [ ] Validar a primeira resposta com âncora pelo WhatsApp

## Noite, se houver fôlego
- [x] Criar o segundo tenant e os dois perfis (três perfis em `consulta/perfis.json`, testados no Neo4j com dados fictícios)
- [x] Registrar consultas e fontes no log (`logs/consultas.jsonl`)

## Amanhã, 9h40–11h
- [x] Testar acesso entre perfis (43 testes automáticos, ver `docs/testes-seguranca.md`)
- [ ] Rodar os ataques de prompt com o agente real e registrar (catálogo em `docs/seguranca/ataques-de-prompt.md`)
- [ ] Isolar as ferramentas do agente no WhatsApp e resolver a corrida de perfil (AP-07, AP-18)
- [ ] Confirmar com o mentor o que "por estado" exige (um estado a mais, ou município mais Estado)
- [ ] Construir site e chat: ver [tasks](specs/001-site-e-chat/tasks.md)
- [x] Completar o README com as instruções de execução

## Amanhã, 11h–12h
- [ ] Ensaiar a demo
- [ ] Fechar slides, premissas, limitações, riscos e próximos passos
- [ ] Enviar os materiais

## Validar com o mentor
1. Portal municipal conta, ou o estadual é obrigatório?
2. Onde o analista perde mais tempo: achar, confirmar a empresa ou documentar a fonte?
3. Os fornecedores dos clientes aparecem nesses portais?
4. Que decisão a resposta alimenta: homologar, bloquear ou renovar?
5. Qual erro é inaceitável: sem fonte, vazamento ou dado desatualizado?
6. O "Obrigatório (até 19h)" do slide 44 vale para hoje?
