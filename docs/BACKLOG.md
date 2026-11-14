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
- [x] Testar acesso entre perfis (65 testes automáticos, ver `docs/testes-seguranca.md`)
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

## Cobertura de CNPJs fora da amostra (combinado em 14/11/2026, um item de cada vez, com verificação)
Motivo: três CNPJs reais testados pelo WhatsApp (Ferreira Costa e dois outros) não foram achados. A base é uma amostra de 100 contratos e o Neo4j do notebook tem hoje a base de exemplo (fictícia).
1. [ ] **CEIS e CNEP** (sanções federais): feito e verificado com dado real, **commitado e enviado** (ver `docs/testes-seguranca.md` §2.7). Falta: decidir se o plano "Único" do site passa a incluir a União (1 linha em `site/setup.php` e os asserts de `site/dev/test_api.py`), reiniciar o worker, subir o worker novo antes de rodar `php site/setup.php` na Hostinger, e rodar ataques e subconjunto do benchmark com a regra 8 nova.
2. [ ] **Cadastro da Receita** (razão social, situação, CNAE): coleta por lista, extração, ferramenta `cadastro_do_fornecedor` e busca por nome fantasia **prontas, verificadas com dado real e commitadas** (`docs/testes-seguranca.md` §2.8). Falta: decidir se o cadastro passa a ser buscado **na hora da pergunta** (hoje é por lista), medir ataques e benchmark com a ferramenta nova, e coletar os CNPJs da demonstração.
3. [ ] **PNCP** (investigado em 14/11, **nada implementado**): a API oficial de consulta **não filtra por fornecedor**; contratos só por data de publicação (**máximo 365 dias**), `cnpjOrgao` ou unidade. Serve para **ampliar os contratos de órgãos escolhidos**, não para consultar um CNPJ qualquer. Medido: Município de Garanhuns (11.303.906/0001-00) tem **55 contratos em 2026** (47 fornecedores, 46 com valor informado) e **nenhum é da Ferreira Costa, da Bernhoeft nem do MEI testado**. A API é lenta (cerca de 15 s por página de 10) e deu erro 500 com página de 100. Antes de implementar: decidir quais órgãos entram e como mapear o `niFornecedor` para o grafo.
4. [ ] **API da Receita Federal** (pedido do Rodrigo, para análise depois): consulta por CNPJ (por exemplo BrasilAPI) ou os arquivos abertos mensais (`dadosabertos.rfb.gov.br`). Só dá identidade da empresa; não traz contrato nem sanção.
5. [ ] **Contratos federais por CNPJ** (`/api-de-dados/contratos/cpf-cnpj` do Portal da Transparência): precisa da chave da API, que ainda não está no `.env`. Passo a passo em `docs/chave-api-portal-transparencia.md`.
