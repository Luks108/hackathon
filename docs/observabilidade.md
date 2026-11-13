# Observabilidade: o que aconteceu com uma pergunta e por que o sistema não respondeu

Objetivo: dada **qualquer pergunta**, reconstruir a jornada inteira em poucos minutos e descobrir se o sistema não respondeu, o que aconteceu, se houve
inconsistência e se alguém tentou atacar o prompt. Sem isso, um problema vira uma hora de sistema fora do ar.

> **Estado (12/11/2026):** implementado e testado (testes automáticos, mutação, e uma pergunta real de ponta a ponta com falhas simuladas; ver o diário
> `docs/sessoes/2026-11-12-rodrigo.md`). A perna do WhatsApp **foi vista com duas mensagens reais** (gateway `recebida` → worker → agente → gateway `envio`, mesmo
> `wa:<id>`, até o alerta `cpf_mascarado`). **Ainda não visto em produção** (Hostinger). Limites conhecidos no fim.

## Em 3 comandos

```bash
python scripts/jornada.py --ultimas        # os últimos desfechos: respondeu? motivo? tempo? modelo?  (pega o request_id)
python scripts/jornada.py --falhas         # só o que NÃO foi respondido, com o motivo classificado e o detalhe
python scripts/jornada.py wa:3EB0A49AA2B2  # a jornada inteira de UMA pergunta, de todos os arquivos, em ordem de horário
```

Outras visões: `--seguranca` (tentativas de ataque), `--saude` (quedas e voltas), `--pasta OUTRA`. A ferramenta só lê; nunca altera nem apaga.

## Os arquivos (um por subsistema, em `logs/`, NDJSON, uma linha por evento)

| Arquivo | Quem escreve | O que registra |
|---|---|---|
| `gateway.jsonl` | gateway do WhatsApp (bun) | início, conexão, queda (com o código), reconexão, mensagem recebida, mensagem técnica ignorada (`debug`), tipo de mídia, tempo de envio |
| `worker.jsonl` | worker | entrada na fila (WhatsApp, com a espera), início (site e WhatsApp, com a espera), texto cortado, timeout e **o desfecho único** de cada pergunta |
| `agente.jsonl` | agente (dentro do worker) | modelo pedido, tentativas, tokens, cache lido e escrito, custo, rodadas, tempo, **troca de provedor com o motivo e o código HTTP** |
| `ferramentas.jsonl` | servidor MCP `transparencia` | qual ferramenta, parâmetros sem dado sensível, duração, quantas linhas voltaram, se voltou vazio |
| `seguranca.jsonl` | worker, agente, servidor MCP e gateway | entrada suspeita (com o trecho que disparou), entrada bloqueada, ferramenta negada, perfil inválido, CPF mascarado, remetente fora da lista |
| `saude.jsonl` | vigia, worker e gateway | cada peça que cai e que volta, com início, fim e duração; passou de 2 minutos fora |

`consultas.jsonl` e `chat.jsonl` continuam como sempre foram (nenhum campo mudou de nome ou formato). O `chat.jsonl` só ganhou campos novos:
`request_id`, `tokens_entrada`, `tokens_saida`, `custo_usd` (quando o provedor informa) e `motivo_falha`.

## Formato de cada linha

```json
{"ts":"2026-11-12T20:36:16.724-03:00","nivel":"info","subsistema":"agente","evento":"tentativa_fim","request_id":"site:4666",
 "tentativa":1,"modelo":"claude-opus-5-5","provedor":"claude","resultado":"ok","duracao_ms":15114,"consultas":5,
 "tokens_entrada":17419,"tokens_saida":692,"cache_lido":12448,"cache_escrito":4963,"custo_usd":0.0561933,"rodadas":6}
```

`ts` (local, com milissegundos e fuso), `nivel` (debug, info, aviso, erro), `subsistema`, `evento`, `request_id` e os campos do evento.

**request_id** acompanha a pergunta do começo ao fim, em todos os arquivos: `wa:<id da mensagem>` no WhatsApp (o gateway e o worker calculam o mesmo valor
sem combinar nada) e `site:<id da pergunta>` no site. O worker o repassa ao gateway em cada pedido de saída, e ao servidor de ferramentas pela variável de
sessão (`TRANSPARENCIA_SESSAO`).

## O desfecho: o campo para olhar primeiro

Cada pergunta termina com **um** evento `desfecho` em `worker.jsonl`: `respondeu` (verdadeiro ou falso) e, se **não** respondeu, o `motivo` classificado:

| motivo | significa | exemplo |
|---|---|---|
| `timeout` | a pergunta estourou o tempo (110 s no total) | "A consulta demorou mais que o esperado." |
| `provedor` | o modelo (ou todos da cadeia) falhou | saldo insuficiente (HTTP 402), chave recusada, limite de uso (429), sem conexão |
| `fila` | o site encerrou a pergunta antes de o worker terminar | resposta tardia descartada pelo site |
| `ferramenta` | uma ferramenta falhou (inclui a transcrição de áudio) | consulta ao grafo com erro; áudio sem transcrição |
| `guardrail` | uma trava do sistema impediu | perfil inexistente; ferramenta fora da lista |
| `interno` | erro do nosso código | exceção inesperada |

Campos úteis do `desfecho`: `canal`, `duracao_ms`, `modelo`, `modelo_pedido`, `trocas`, `consultas`, `fontes`, `detalhe` (a frase curta do erro) e, quando o
provedor informou, `tokens_entrada`, `tokens_saida`, `custo_usd`. Mensagens que o worker resolve **sem agente** (tipo não suportado, áudio ilegível, texto
vazio) também fecham com `desfecho`, com `via` (`sem_agente` ou `ignorada`) e a `razao`. Texto vazio é ignorado e **não** é falha (`motivo` nulo).

## Quando algo quebrou: o roteiro de cinco minutos

1. `python scripts/jornada.py --saude` → alguma peça caiu? Início, fim e duração de cada queda. Peça fora por mais de 2 minutos aparece como
   `componente_fora_alem_do_limite` (nível `erro`).
2. `python scripts/jornada.py --falhas` → o que não foi respondido, com o motivo e o detalhe.
3. `python scripts/jornada.py <request_id>` → a jornada completa: chegada no gateway, espera, início, cada tentativa de modelo, cada ferramenta, o fim.
4. `python scripts/jornada.py --seguranca` → houve tentativa de ataque? O trecho que disparou está no log.
5. Na troca de provedor, o evento `troca_de_provedor` traz `causa` (credito, limite, chave, tempo, servidor, rede, vazia, outro) e `codigo_http`.

## Eventos por subsistema

- **gateway:** `iniciou`, `conectado`, `queda` (código e nome do motivo), `reconectado` (duração da queda), `deslogado`, `recebida`, `ignorada_tecnica` (debug),
  `tipo_nao_tratado`, `midia_recebida` (tipo, bytes, baixada, tempo), `envio` (op, ok, duração; `reagir` e `digitando` em debug), `sem_confirmacao_reenviando`,
  `sem_confirmacao_apos_reenvio`, `erro_nao_tratado`, `encerrou`.
- **worker:** `entrada_na_fila`, `inicio`, `texto_cortado`, `timeout`, `desfecho`.
- **agente:** `inicio`, `tentativa_inicio`, `chamada_modelo` (só nos modelos de API: debug se deu certo, aviso se falhou), `tentativa_fim`, `troca_de_provedor`, `resumo`.
- **ferramentas:** `chamada`.
- **seguranca:** `entrada_suspeita`, `cpf_mascarado`, `injecao_em_fonte`, `injecao_em_argumento`, `entrada_bloqueada`, `ferramenta_negada`,
  `ferramentas_nao_autorizadas`, `evidencia_negada`, `perfil_invalido`, `remetente_nao_autorizado`.
- **saude:** `componente_iniciou`, `componente_parou`, `componente_caiu`, `componente_fora_alem_do_limite`, `componente_voltou`, `vigia_iniciou`, `vigia_parou`,
  `vigia_ficou_cego`.

## Saúde: como o "fora do ar por mais de 2 minutos" fica escrito

O **vigia** (`chat/vigia.py`, sobe junto com o `ligar-tudo`) é um processo separado, porque quem caiu não consegue avisar. A cada 15 s ele olha:

| Peça | Como sabe que está viva |
|---|---|
| worker | batimento em `logs/saude-worker.json`, renovado a cada 10 s (parado há mais de 45 s = fora) |
| gateway | campo `atualizado` do `status.json`, renovado a cada 30 s (mais de 90 s sem mudar = fora), e `conectado` |
| site | `GET {API_BASE}/api/me` (qualquer resposta abaixo de 500 conta como no ar) |
| neo4j | conexão TCP com o `NEO4J_URI` |

A queda conta **do último sinal de vida**, não de quando o vigia notou: `componente_caiu` traz `desde` (o início real) e `detectado_em`. Quando passa de
`VIGIA_LIMITE_S` (padrão 120 s) escreve `componente_fora_alem_do_limite` **uma vez**. Quando volta, escreve `componente_voltou` com `inicio_queda`, `fim_queda`,
`duracao_s` e `passou_do_limite`. O estado fica em `logs/saude-estado.json`: se o vigia reiniciar no meio de uma queda, ela continua contando do início certo.

Exemplo real (worker derrubado à força, 12/11/2026):

```
20:38:39  aviso  componente_caiu                 componente=worker desde=20:37:54.480 detectado_em=20:38:39.969 motivo=sem batimento há 45 s
20:39:55  erro   componente_fora_alem_do_limite  componente=worker fora_ha_s=120.6 limite_s=120.0
20:40:02  aviso  componente_iniciou               componente=worker lacuna_s=127.6 parada_limpa=false fora_ha_mais_de_2min=true   (escrito pelo próprio worker ao voltar)
20:40:10  info   componente_voltou                componente=worker inicio_queda=20:37:54.480 fim_queda=20:40:10.070 duracao_s=135.6 passou_do_limite=true
```

## Configuração (`.env`; os padrões servem)

| Variável | Padrão | Para quê |
|---|---|---|
| `LOG_NIVEL` | `info` | `debug`, `info`, `aviso` ou `erro` |
| `LOG_MAX_MB` | `10` | cada arquivo gira ao passar disso (`x.jsonl` vira `x.jsonl.1`, e assim por diante) |
| `LOG_ARQUIVOS` | `5` | quantas cópias giradas guardar |
| `FORNEXIA_LOGS_DIR` | `logs/` | outra pasta |
| `VIGIA_INTERVALO_S` / `VIGIA_LIMITE_S` | `15` / `120` | de quanto em quanto tempo olha / depois de quantos segundos fora alerta |
| `VIGIA_COMPONENTES` | `gateway,worker,site,neo4j` | o que vigiar (em outra máquina, tire o que não existe lá) |

## O que nunca vai para o log

Chave, token, senha, telefone, CPF, e-mail e o **texto de uma mensagem**. Garantido por uma regra central (`consulta/registro.py` e `canal-whatsapp/registro.ts`,
a mesma nos dois lados e testada nos dois): campos com nome sensível (`chave`, `token`, `senha`, `telefone`, `remetente`, `chat_id`, `texto`, `mensagem`,
`pergunta`, `resposta`, `conteudo`...) viram `[omitido]`, e todo texto solto passa por uma máscara (`[CPF]`, `[TEL]`, `[EMAIL]`, `[SEGREDO]`). O nome é conferido por
**trecho** (pega o plural e as variações: `telefones`, `mensagens`...), e a única exceção são as contagens conhecidas (`tokens_entrada`, `tokens_saida`,
`tokens_total`, `tamanho_*`, `qtd_*`, `*_len`, `*_bytes`, `*_ms`, `*_s`), para `tokens_entrada` e `tamanho_texto` passarem. Para ver "o mesmo remetente tentou 5 ataques" sem gravar o telefone, o log usa um
apelido (`ator`): um HMAC com um sal que fica só em `logs/.sal-ator` (apagar o sal troca todos os apelidos). O único trecho de texto de usuário que entra é o
**trecho curto que disparou um alerta de segurança** (até 120 caracteres, já mascarado), porque é isso que permite ver a tentativa depois.

Tokens, cache e custo só aparecem quando o provedor os **informa**; nada é estimado nem completado. O custo dos modelos DeepSeek depende da tabela de preços em
`chat/provedores.py`; sem preço, o campo fica ausente.

## Limites conhecidos (não escondidos)

- **A espera na fila do site depende do site novo.** `POST /api/worker/proxima` agora devolve `espera_ms` (do `criada_em` até a reserva, medido pelo banco). Contra um site **antigo**
  (sem o campo, por exemplo a hospedagem antes do próximo deploy) o worker grava `espera_ms: null`, nunca zero.
- **`espera_ms` do WhatsApp tem precisão de ±1 s, para mais.** O horário que o WhatsApp entrega (`ts`) vem em segundos inteiros e o worker consulta a fila em ritmo
  fixo; em duas mensagens reais deu `1077` nas duas, quando o intervalo real entre `recebida` (gateway) e `entrada_na_fila` (worker) foi de 757 ms e 433 ms. Para o
  valor fino, use a diferença entre esses dois eventos no `scripts/jornada.py`.
- **O vigia pode estar parado.** Se ele mesmo cair, ninguém escreve; ao voltar, registra `vigia_ficou_cego` com o intervalo. Ele sobe e desce com o
  `ligar-tudo` e o `parar-tudo`.
- **Atraso de detecção.** `componente_voltou` é escrito no próximo passo do vigia (até 15 s depois da volta real); o `componente_iniciou` do próprio worker ou
  gateway tem o instante exato. Um gateway **antigo** (de antes desta versão) não renova o `status.json` e parece "sem sinal" depois de 90 s: reinicie-o.
- **Matar à força não escreve `componente_parou`** (só a parada limpa escreve); o vigia e a lacuna do início seguinte cobrem esse caso.
- **O detector de ataques é por padrões** (`consulta/deteccao.py`), em português e inglês: só observa e registra, nunca bloqueia. Ataque novo ou ofuscado pode passar
  (um padrão novo é uma linha). Pode haver falso positivo.
- **`chamada_modelo` (tempo de cada ida ao provedor) só existe nos modelos de API** (DeepSeek e afins). No Claude pelo CLI o provedor só informa o total
  (`duracao_api_ms`, `rodadas`).
- **Logs locais**, em arquivos: não há painel nem alerta externo. O ganho é poder reconstruir uma pergunta; avisar por e-mail ou WhatsApp quando algo cai é outro passo.
- Em Windows, se outro processo estiver com o arquivo aberto na hora de girar, a rotação espera a próxima gravação.
