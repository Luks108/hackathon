# Diário de sessões: o que foi feito e o que ficou em aberto

Cada pessoa (ou agente de IA trabalhando para ela) que mexe no projeto deixa **um arquivo aqui** ao terminar. Quem baixa as
atualizações lê os mais recentes e já sabe o que mudou, em que estado está e o que falta, sem refazer a análise do zero.
Vale para qualquer ferramenta (Claude Code, Codex, Cursor, Copilot, Gemini, à mão): o formato é texto e a regra é a mesma.

## Padrão fixo (toda ferramenta e todo provedor cria o diário do mesmo jeito)

> **Para o agente de IA que está lendo isto, seja qual for o provedor:** o diário **nunca** é escrito do zero nem com estrutura própria.
> Você o cria **sempre copiando [`_modelo.md`](_modelo.md)**, mantendo **os mesmos títulos, na mesma ordem**, e só preenchendo o conteúdo:
>
> ```bash
> cp docs/sessoes/_modelo.md docs/sessoes/AAAA-MM-DD-usuario.md     # troque a data e o usuário; ajuste a 1ª linha do arquivo
> python docs/sessoes/validar.py docs/sessoes/AAAA-MM-DD-usuario.md  # tem que terminar em "ok"
> ```
>
> Não renomeie seções, não troque a ordem, não apague seção (escreva "Nenhum" se não houver conteúdo), não crie outro formato nem outra pasta.
> O validador confere nome, título, campos, seções e a presença de segredo. O hook de commit roda o mesmo validador e **bloqueia** o commit
> se o diário estiver fora do padrão.

**Ative o hook uma vez em cada clone** (ele não vai no `git clone` sozinho): `git config core.hooksPath .githooks`. Sem isso, o validador
só roda se você o chamar. O hook também **avisa** (sem bloquear) quando um commit muda código e nenhum diário vai junto.

## Para quem vai começar a trabalhar (leia antes de mexer)

1. Rode `git pull` e liste esta pasta: `ls docs/sessoes`.
2. Leia **os 3 arquivos mais recentes** (a data está no nome). O **mais recente é a fonte da verdade** dos itens em aberto.
3. Confira o estado real antes de confiar no texto: `git log --oneline -10` e `git status`. O diário diz o que se sabia na hora;
   o código é o que vale. Se algo divergir, diga isso ao usuário.
4. Não refaça o que já está marcado como feito e verificado. Retome pelos itens em aberto, na ordem de prioridade.

## Para quem terminou de trabalhar (obrigatório)

Antes de encerrar a sessão, ou a cada bloco de trabalho relevante, crie ou atualize o seu arquivo do dia.

- **Nome:** `AAAA-MM-DD-usuario.md`, por exemplo `2026-11-10-rodrigo.md`.
  - `usuario` é o `git config user.name`. Se estiver vazio, use o login do sistema (`$USER` no Linux, `%USERNAME%` no Windows). Se
    nada disso existir, pergunte. Escreva em minúsculas, sem acento e sem espaço (use `-`).
  - **Um arquivo por pessoa por dia.** Se já existe o de hoje, acrescente uma seção `## Sessão 2` no fim, em vez de criar outro.
  - Nunca edite o arquivo de outra pessoa nem o de outro dia: isso evita conflito no git. Se um item de um arquivo antigo foi
    resolvido, registre no **seu** arquivo, na seção "Resolvido de sessões anteriores".
- **Itens em aberto:** copie para o seu arquivo todo item ainda aberto dos arquivos anteriores, com a origem entre parênteses,
  e **retire** o que foi resolvido. Assim, o arquivo mais recente basta para saber o que falta.
- **Vai junto do commit** do trabalho que descreve (mesmo commit ou o seguinte do mesmo push).
- **Seja fiel.** Diga o que foi verificado e como, e o que **não** foi (não rodou, sem a máquina, sem o serviço). Número de teste
  sem a data e a máquina em que rodou não vale. Não escreva "pronto" para o que só foi escrito.

### O que nunca entra neste diário (ele é versionado)

Chaves de API, conteúdo do `.env`, senhas, tokens, `WORKER_KEY`, números de telefone (do bot ou de pessoas), CPF, e-mails
pessoais, caminhos com dado sensível e trechos de dados reais com pessoa física. Cite só **o nome** da variável ou do arquivo.

## Modelo do arquivo

A única fonte do formato é [`_modelo.md`](_modelo.md). Seções, nesta ordem: **Resumo, Feito, Verificado (e como), Não verificado,
Decisões e motivo, Em aberto (por prioridade), Resolvido de sessões anteriores, Armadilhas, Próximo passo sugerido.** Campos do
começo: **Quem, Branch e commit de partida, Máquina e ambiente.** Mudou o padrão? Mude `_modelo.md` e `validar.py` juntos, no mesmo commit.

Mantenha cada arquivo curto (uma página ou duas). Detalhe longo vai para `docs/` e o diário só aponta para ele.
