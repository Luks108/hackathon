# Desenvolvimento local do site

PHP 8.2 e MariaDB, os mesmos da hospedagem. Tudo roda na sua máquina.

## Primeira vez

```bash
# 1. Banco (Docker). Escuta só em 127.0.0.1:3307
docker compose -f site/dev/docker-compose.yml up -d

# 2. Configuração local (o arquivo é ignorado pelo git)
cp site/hackathon-config.exemplo.php site/hackathon-config.php
#    troque WORKER_KEY por uma chave aleatória de 24+ caracteres

# 3. Tabelas, planos e um administrador de teste
php site/setup.php admin@local.test "Admin Local" senha-local-123
```

## Administrador

**Só para desenvolvimento** (banco local, nada disso vale no site publicado):

| E-mail | Senha |
|---|---|
| `admin@local.test` | `senha-local-123` |

Se a senha deixar de funcionar, o `setup.php` a redefine (rodar de novo com outra senha **troca** a senha do admin):

```bash
php site/setup.php admin@local.test "Admin Local" senha-local-123
```

**No site publicado não existe admin padrão.** O admin é criado pelo Lucas, no deploy, com uma senha só dele:

1. No `.env` do notebook: `ADMIN_EMAIL=...` e `ADMIN_SENHA=...`. A senha precisa ter **12 caracteres ou mais** e não pode ser uma
   senha comum. Em produção o `setup.php` recusa as fracas.
2. `./site/deploy.sh --setup`

Para testar no site publicado, peça a senha ao Lucas. Não a coloque em arquivo do repositório nem em mensagem de commit.

O admin entra em `/admin.html` para aprovar e bloquear telefones do WhatsApp (A09 e A16), e usa o chat como qualquer conta.

Sem PHP no Windows: `winget install PHP.PHP.NTS.8.2`. Depois ative `pdo_mysql`, `curl`, `fileinfo`, `openssl` e `mbstring` no `php.ini`.

## Rodar

```bash
php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php     # o site em http://127.0.0.1:8080
python site/dev/worker_falso.py                                   # responde às perguntas com um roteiro fixo
```

Abra `http://127.0.0.1:8080/chat.html`, crie uma conta, ative um plano e pergunte. O `router.php` faz o papel do `.htaccess`
(manda `/api/*` para `api/index.php`).

O worker falso muda de roteiro conforme a pergunta: "erro" termina com um evento de erro, "lento" não responde (para ver o
limite de tempo) e "sem fonte" responde sem citar fonte. O worker real, do Dev B, usa as mesmas rotas.

## Testes

```bash
python site/dev/test_api.py       # 78 testes contra PHP e MariaDB de verdade; PHP_BIN=/caminho/php.exe se preciso
```

Os testes sobem os próprios servidores PHP e limpam o que criam. Cobrem os critérios de aceite de A01 a A09, incluindo a
corrida entre dois workers, a abertura simultânea de perguntas e de telefones, os limites de tempo e o acesso do administrador.

## Rotas

O contrato completo está em [`docs/specs/001-site-e-chat/plan.md`](../../docs/specs/001-site-e-chat/plan.md).

## Zerar o banco

```bash
docker compose -f site/dev/docker-compose.yml down -v && docker compose -f site/dev/docker-compose.yml up -d
php site/setup.php
```

## Páginas do site

| Página | O que é |
|---|---|
| `/` | Página inicial, com o assistente flutuante |
| `/chat.html` | Chat em tela cheia (entrar, criar conta e conversar) |
| `/conta.html` | Minha conta: dados, plano e telefones do WhatsApp com o estado de cada um |
| `/admin.html` | Administração (só papel `admin`): fila de telefones, aprovar e bloquear em um clique |

O link "Administração" só aparece para quem é admin, e o servidor recusa as rotas de qualquer jeito (`403`).
Para testar como administrador em desenvolvimento, use a conta da seção "Administrador" acima.
