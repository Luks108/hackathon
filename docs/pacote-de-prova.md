# Pacote de prova exportável: registro de trabalho

> Movido do `CLAUDE.md` em 10/11/2026: é um diário do que foi feito e decidido em 08/11/2026, não instrução para a sessão. As contagens de
> testes abaixo são as daquela data (hoje `chat/testes` tem 65 testes, com os de robustez do worker).

## Pacote de prova exportável (08/11/2026)

Um ZIP que um terceiro (auditor, compliance, banca) baixa e reconfere sem acesso ao sistema. Rotas: `GET /api/perguntas/{id}/prova`
(uma consulta) e `GET /api/provas[?ids=1,2,3]` (dossiê, na ordem). Botão "Exportar prova" em `chat.js`, ao lado da resposta.
`?formato=json` devolve só o JSON.

### O que o levantamento achou (item 2)
- **(a) `conferir_evidencia`** (`consulta/mcp_transparencia.py:324`) devolve `trecho`, `url`, `arquivo`, `documento_hash`, `tabela`, `linha`,
  `capturado_em` (texto), `trecho_mascarado` e `hash_confere` (booleano recalculado a cada chamada). **Não existe hash do trecho** no grafo.
  O evento `fonte` que chegava ao site só levava `evidencia`, `trecho`, `url`, `capturado_em` e `hash_confere`: faltava a cadeia até o bruto.
- **(b) Logs.** `logs/consultas.jsonl` (MCP, uma linha por tool): `ts, sessao, perfil, tenants, ver_pessoal, tool, args, resultados, evidencias,
  duracao_ms, erro`; `sessao` é sempre `null`. `logs/chat.jsonl` (worker, uma linha por pergunta): `em, canal, id, usuario, tenants, pergunta,
  consultas, evidencias, desfecho, modelo_pedido, modelo, tentados, trocas, primeiro_sinal_ms, duracao_ms`. **Nenhum guarda a resposta nem o trecho.**
  Resposta e fontes ficam no banco do site (`eventos`), e o worker roda em outra máquina: por isso a exportação nasce no PHP.
- **(c) Hash do bruto:** SHA-256 do arquivo inteiro, em `Evidencia.documento_hash` (`coleta/extrair.py:131`), recalculado na conferência.
- **(d) Versão do extrator: não existe** em lugar nenhum. O pacote traz `versao_extrator: null` com a explicação.
- **(e) Download:** não havia rota de download para o usuário (só `rota_painel`, que usa `readfile`). Criei as rotas acima.

### Formato e por quê
ZIP com `prova.json` + `LEIA-ME.txt` + `trechos/*.txt` + `verificar_prova.py` (opcional). Um auditor não técnico abre o ZIP e o texto no
Explorador, e cada trecho vira um arquivo `.txt` com os bytes exatos, então `Get-FileHash`/`certutil`/`sha256sum` batem com o JSON sem ferramenta nossa.
O ZIP é gravado por um escritor mínimo em PHP (sem compressão), porque o PHP local não tem a extensão `zip`.

### Arquivos
- Criados: `site/public_html/api/lib_prova.php`, `site/dev/test_prova.py`, `chat/testes/test_prova_dados.py`.
- Alterados: `site/public_html/api/index.php` (rotas), `site/public_html/assets/chat.js` e `site.css` (botão), `site/public_html/chat.html` (cache),
  `chat/agente.py` (o evento `fonte` ganhou `documento_hash`, `arquivo` só com o nome, `tabela`, `linha`, `trecho_mascarado`), `chat/worker.py`
  (o `fim` e o `erro` passam a levar `modelo_pedido`, `modelo`, `tentados`, `trocas`), `README.md` e este arquivo. Só acréscimos: nenhum campo
  antigo, nenhum teste antigo e nenhum formato de log mudou. O banco não mudou.

### Resultados dos testes
- `site/dev/test_prova.py` (novo, PHP + MariaDB reais): **33 OK** (22 na primeira entrega + 11 da rodada de correções, abaixo), rodados 3 vezes seguidas. Cobrem os seis pontos pedidos: campos preenchidos, hash
  recalculado, "sem prova" sem dado emprestado, consulta inexistente (404, sem arquivo), dossiê de 3 em ordem sem duplicar, ausência de segredo
  e de caminho interno. Mais: adulteração detectada, trecho sem cadeia completa vira `prova_incompleta`, fallback registrado, só o dono lê, login, ids inválidos.
- `chat/testes`: **50 OK** (eram 42; 8 novos). `consulta/testes`: **65 OK**. Fumaça no navegador: **4/4**.
- `site/dev/test_api.py`: **79 de 80**. A falha é `test_dois_pedidos_ao_mesmo_tempo_nao_pegam_a_mesma_pergunta` (78 != 80): há dois
  `chat/worker.py` reais rodando e consultando `127.0.0.1:8080` (o mesmo banco), e eles pegaram 9 perguntas de teste na janela da rodada.
  Não mexi nesse teste nem nesses processos. Os testes novos são imunes: criam a pergunta já fora da fila.
- Demonstração: pacote real aberto pelo `Expand-Archive` do Windows; o hash do trecho bateu por `Get-FileHash` e por `certutil`; um arquivo bruto
  errado dá hash diferente do `documento_hash`.

### O que ficou de fora e por quê
- **O arquivo bruto não vai no pacote.** Pode ter dado pessoal que o perfil não vê, e o bruto fica no notebook, não no site. O auditor o pede
  e confere o `documento_hash` (`verificar_prova.py --bruto PASTA` ajuda). Sem o bruto, o pacote só prova a integridade do trecho, não a origem.
- **`trecho_sha256` é calculado na exportação** (o grafo não guarda hash do trecho). Protege contra alteração posterior; a origem é o `documento_hash`.
- **Versão do extrator:** ausente. Registrá-la exige gravar a versão em cada `Evidencia` e recarregar o grafo.
- **Só os trechos conferidos** (no máximo 3 por resposta) entram. Conferem o modelo (regra do agente) e, desde 13/11/2026, o **código**: se a resposta cita um fato (número do contrato, valor ou nome) cuja evidência o modelo não abriu, ela é aberta ao fim pelo mesmo filtro de perfil (`consulta/prova.py`) e vem marcada `automatica`. Fato que a resposta não cita não gera trecho, e fato sem evidência nas tools (a contagem de `cobertura`, o nome por CNPJ de `buscar_fornecedor`) continua sem trecho.
- Consultas feitas **antes** desta mudança saem com modelo/troca `null` e `prova_incompleta` (o `fonte` antigo não tem `documento_hash`).
- Exportação pelo WhatsApp, "sessão" no servidor (o site não tem; o dossiê é por conta ou por ids) e assinatura digital do pacote.
- Não rodei prova real de fallback nem pergunta com modelo real (nenhum token gasto por mim neste trabalho).

### O que você precisa decidir antes de commitar
1. **Os dois workers reais rodando no notebook** respondem com modelo de verdade qualquer pergunta que apareça na fila do `:8080`, inclusive
   as dos testes da API (9 na última rodada), e isso gasta token. Vale parar um deles ou apontá-los para outro banco enquanto se testa.
2. **Expor o modelo e as trocas no `fim`/`erro`:** o navegador também recebe esses campos em `/eventos` (a tela os ignora). É o que permite o
   pacote registrar a troca; se não quiser, o caminho alternativo é só o worker gravar no log e o pacote sair sem modelo.
3. **Incluir o arquivo bruto** em exportações feitas no notebook (CLI), só para dados fictícios ou perfis que podem ver tudo?
4. **Registrar a versão do extrator** na coleta (muda o grafo e exige recarga).
5. **Revisar `lib_prova.php`** antes do commit: é a parte nova mais sensível (lê o banco e monta o download).

### Rodada de correções do pacote de prova (08/11/2026)

**Parte A, ambiente: DIVERGENTE, nada foi derrubado.** O que estava de pé: Docker com `hackathon-site-db` (`mariadb:10.11`, porta 3307) e
`hackathon-neo4j` (`neo4j:5.26.0-community`); fora do Docker, `php -S 127.0.0.1:8080` (PID 37720) e `chat\worker.py` em **dois** PIDs: 38492
(lançador do venv do Windows) e seu filho 17612 (o interpretador), ambos iniciados às 17:18:12. **É um worker só**, não dois. Derrubar qualquer
um dos dois PIDs seria ficar sem worker. O que rouba as perguntas de teste são os **3 agentes** desse único worker (`AGENTES_SITE=3`, `chat/worker.py:44`),
todos consultando a fila do mesmo banco. Sobrou o mesmo worker e o site responde (`/api/saude` 200; o worker seguiu pegando perguntas às 21:38).
Para ter 80 de 80: parar o worker enquanto roda `test_api.py`, ou apontá-lo para outro banco.

| Item | Situação | Onde |
|---|---|---|
| B.1 ordem dos ids | **Feito**: vale a ordem pedida; ids repetidos saem uma vez (primeira ocorrência) | `lib_prova.php`: `prova_registros` (sem `sort`), `rota_provas` (`array_unique`), comentário de cabeçalho |
| B.2 byte inválido | **Feito, com ressalva**: o byte vira U+FFFD **antes** do hash, no arquivo do trecho e no JSON, e o JSON tem `JSON_INVALID_UTF8_SUBSTITUTE`; o verificador passa | `prova_utf8()`, `prova_trecho`, `prova_registro`, `prova_pacote`. Ressalva: pela API e pelo banco o byte inválido **não chega** (o `json_decode` recusa e a coluna do MariaDB também), então é defesa em profundidade, testada direto na função via `php -r` |
| B.3 `dados_pessoais` | **Feito pela opção 2**: sai `null` com nota "Não avaliado". Não há detector confiável (só regex de CPF: `coleta/extrair.py:38`, `consulta/mcp_transparencia.py:71`, `gerar_painel.py:24`, `pagina_do_grafo.py:22`, que não pegam nome de pessoa) | `prova_registro`, `PROVA_SEM_AVALIACAO_PESSOAL`, LEIA-ME. A tela não prometia nada sobre isso, então não mudou |
| C.1 `hash_confere` | **Feito**: aceita o booleano `true` e o inteiro `1`, nada além. O worker real grava `true` (`bool()` em `chat/agente.py:215`); o `worker_falso` nem envia o campo. `1.0` chega como `1` porque o `json_encode` do PHP o normaliza ao gravar | `prova_trecho` (`in_array(..., [true, 1], true)`) |
| C.2 N+1 | **Feito**: **204 → 6 consultas ao banco e 235 → 25 ms** para um dossiê de 100 consultas (medido, 3 rodadas, melhor delas) | `prova_registros` (um `IN` para perguntas e outro para eventos) |
| C.3 tamanho | **Feito**: teto de **5 MB** (soma dos bytes do pacote, antes de zipar). Acima, **422** com "Pacote grande demais… Reduza o número de consultas". Corte antecipado em 4x o teto ao ler os eventos | `PROVA_MAX_BYTES`, `prova_grande_demais`, `prova_enviar`, `prova_registros` |
| C.4 verificador | **Feito**: a pasta de brutos é opcional (`--bruto` sem valor usa `bruto/` ao lado; sem a opção, usa `bruto/` se existir). Sem ela, imprime "ATENÇÃO: a origem de N trecho(s) NÃO foi conferida" e o LEIA-ME explica | `PROVA_VERIFICADOR`, `prova_leia_me` |
| C.5 resposta vazia | **Feito**: sem texto (ou só espaço), sai `sem_prova` e `resposta: null`; o trecho continua listado | `prova_registro` |

**Testes.** `site/dev/test_prova.py`: **33 OK** (eram 22; 11 novos), 3 rodadas seguidas. `chat/testes` 50 OK, `consulta/testes` 65 OK, fumaça 4/4.
`site/dev/test_api.py`: **79 de 80**. Continua falhando só `test_dois_pedidos_ao_mesmo_tempo_nao_pegam_a_mesma_pergunta` (**78 != 80**): o worker
único pegou 8 perguntas na janela da rodada. Como nada foi derrubado, esse número não mudou. Dois testes **meus** mudaram porque descreviam o
comportamento antigo (a ordem numérica do dossiê e `dados_pessoais` falso); nenhum teste das outras suítes foi tocado.

**O que ficou pior ou mais frágil.**
- `dados_pessoais: null` diz menos do que o `false` de antes (o `false` era uma promessa sem lastro).
- O verificador sai com código 0 quando a origem não foi conferida (só avisa por texto). Quem lê só o código de saída pode achar que tudo foi provado.
- O teste de N+1 usa o contador global do MariaDB; com o worker real consultando o mesmo banco ele tem ruído (margem larga: ~6 consultas contra o limite de 30), mas pode oscilar.
- O teste do teto grava ~3 MB no banco a cada rodada (apagados no `setUp`/`tearDownModule`).
- O 422 para "grande demais" é uma escolha minha (o 413 é para requisição grande, não para resposta).
