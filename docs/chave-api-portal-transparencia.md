# Chave da API do Portal da Transparência (passo a passo)

Para que serve aqui: a rota `/contratos/cpf-cnpj` devolve **contratos federais de um fornecedor pelo CNPJ** (item 5 do `docs/BACKLOG.md`).
O CEIS e o CNEP **não precisam** da chave: entram pelos arquivos em lote (`python coleta/federal.py`, `docs/testes-seguranca.md` §2.7).

**O que é fato e o que não foi confirmado.** Confirmado na especificação oficial (`https://api.portaldatransparencia.gov.br/v3/api-docs`, lida em 14/11/2026): a chave vai no cabeçalho HTTP `chave-api-dados` e o cadastro fica em
`https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email`. **Não confirmado:** o que o formulário pede (só e-mail, ou login gov.br), e o limite de requisições por minuto (a especificação não diz).
O portal não deixa um programa abrir essa página (responde com um desafio anti-robô), então o passo 1 é no navegador, por uma pessoa.

## Passo a passo

1. **Abra no navegador** `https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email`. Se a página não abrir, vá em `https://portaldatransparencia.gov.br/api-de-dados` e procure o cadastro.
2. **Cadastre um e-mail que você lê** (de preferência um do projeto, não o pessoal) e preencha o que o formulário pedir. Se pedir login gov.br, entre com a sua conta.
3. **A chave chega por e-mail** (confira o spam; não sei quanto demora, porque não consegui abrir o formulário para ver). Ela é uma sequência longa de letras e números.
4. **Guarde só no `.env`**, na raiz do projeto, numa linha nova, **sem aspas e sem espaço**:
   ```
   PORTAL_TRANSPARENCIA_CHAVE=cole-a-chave-aqui
   ```
   O `.env` está no `.gitignore`. A chave **nunca** vai para o código, o chat, o diário (`docs/sessoes`), a memória nem uma mensagem de commit. Se vazar, peça outra no mesmo formulário.
5. **Teste com uma única chamada** (não em laço). No Git Bash, na raiz do projeto:
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -H "chave-api-dados: $(grep '^PORTAL_TRANSPARENCIA_CHAVE=' .env | cut -d= -f2- | tr -d '\r')" "https://api.portaldatransparencia.gov.br/api-de-dados/ceis?pagina=1"
   ```
   - `200`: a chave vale.
   - `401`: chave errada ou colada com espaço/aspas (confira a linha do `.env`).
   - `429`: passou do limite; espere alguns minutos e tente de novo, **uma vez**.
   - Qualquer outra coisa: pare e avise, não repita em laço.
6. **Avise o Dev A** que a chave está no `.env` (sem mandar a chave). O código do item 5 (`/contratos/cpf-cnpj`) ainda **não existe**: este passo só deixa a chave pronta.

## Cuidados
- Use a chave **só** nesta máquina (o `.env` não é copiado). Cada pessoa que for rodar a coleta cadastra a sua.
- Respeite o limite: pausa entre chamadas e parar no primeiro `429`, como fazem `coleta/federal.py` e `coleta/receita.py`.
- Na linha de comando acima a chave fica visível a outros processos da mesma máquina enquanto o `curl` roda. Em máquina compartilhada, não rode assim.
