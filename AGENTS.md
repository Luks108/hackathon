# Instruções para agentes de IA (Codex, Cursor, Copilot, Gemini, Claude e outros)

O contexto do projeto, os comandos e as regras estão em [`CLAUDE.md`](CLAUDE.md) e no [`README.md`](README.md). Leia os dois.

## Diário de sessões (obrigatório)

1. **Ao começar:** `git pull`, depois leia os 3 arquivos mais recentes de [`docs/sessoes/`](docs/sessoes/LEIAME.md). O mais recente é a fonte
   da verdade dos itens em aberto. Confira com `git log` e `git status`: o código vale mais que o texto.
2. **Ao terminar** (ou a cada bloco relevante de trabalho): crie ou atualize `docs/sessoes/AAAA-MM-DD-usuario.md`.
   **Sempre copie `docs/sessoes/_modelo.md`, com os mesmos títulos na mesma ordem; nunca invente outro formato.** Depois rode
   `python docs/sessoes/validar.py docs/sessoes/AAAA-MM-DD-usuario.md` (deve dar `ok`). `usuario` é o `git config user.name`; se estiver vazio,
   o login do sistema. Um arquivo por pessoa por dia; não edite o de outra pessoa.
   Uma vez por clone: `git config core.hooksPath .githooks` (o hook roda o validador e bloqueia o commit fora do padrão).
3. Diga no diário o que foi **verificado** (com o comando e a máquina) e o que **não** foi. Copie para o seu arquivo os itens ainda em aberto dos anteriores.
4. **Nunca** escreva no diário chave de API, conteúdo do `.env`, senha, token, número de telefone, CPF ou e-mail pessoal.
