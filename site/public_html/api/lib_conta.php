<?php
// Conta: cadastro, login com limite de tentativas, logout, planos e assinatura.

declare(strict_types=1);
if (!defined('API')) { http_response_code(404); exit; }

const LOGIN_MAX_POR_EMAIL_E_IP = 5;    // falhas em 15 minutos
const LOGIN_MAX_POR_IP = 20;
const LOGIN_MAX_POR_EMAIL = 30;        // limite global do e-mail: segura ataque vindo de muitos IPs

function usuario_atual(): ?array {
    static $cache = false;
    if ($cache !== false) return $cache;
    $id = (int)($_SESSION['uid'] ?? 0);
    if ($id <= 0) return $cache = null;
    $st = db()->prepare('SELECT id, nome, email, papel FROM usuarios WHERE id = ?');
    $st->execute([$id]);
    $u = $st->fetch() ?: null;
    if ($u === null) unset($_SESSION['uid']);   // conta apagada: a sessão deixa de valer
    return $cache = $u;
}

function exigir_login(): array {
    $u = usuario_atual();
    if ($u === null) erro(401, 'Faça login para continuar.');
    return $u;
}

function exigir_admin(): array {
    $u = exigir_login();
    if ($u['papel'] !== 'admin') erro(403, 'Acesso restrito ao administrador.');
    return $u;
}

function plano_para_json(array $p): array {
    return [
        'id' => (int)$p['id'],
        'nome' => $p['nome'],
        'preco_mensal' => (float)$p['preco_mensal'],
        'franquia' => (int)$p['franquia'],
        'preco_excedente' => (float)$p['preco_excedente'],
        'tenants' => json_decode((string)$p['tenants'], true) ?: [],
    ];
}

/** Plano da assinatura ativa do usuário, ou null. */
function plano_ativo(int $usuarioId): ?array {
    $st = db()->prepare('SELECT p.* FROM assinaturas a JOIN planos p ON p.id = a.plano_id
                         WHERE a.usuario_id = ? AND a.status = "ativa" ORDER BY a.id DESC LIMIT 1');
    $st->execute([$usuarioId]);
    $p = $st->fetch();
    return $p ? plano_para_json($p) : null;
}

function entrar(int $usuarioId): void {
    session_regenerate_id(true);   // evita fixação de sessão
    $_SESSION['uid'] = $usuarioId;
    $_SESSION['csrf'] = bin2hex(random_bytes(32));
}

// ---------- limite de tentativas ----------

function contar_falhas(string $campo, string $valor, ?string $email = null): int {
    $sql = "SELECT COUNT(*) FROM tentativas_login WHERE $campo = ? AND criada_em > NOW() - INTERVAL 15 MINUTE";
    $args = [$valor];
    if ($email !== null) { $sql .= ' AND email = ?'; $args[] = $email; }
    $st = db()->prepare($sql);
    $st->execute($args);
    return (int)$st->fetchColumn();
}

function login_bloqueado(string $email, string $ip): bool {
    return contar_falhas('ip', $ip, $email) >= LOGIN_MAX_POR_EMAIL_E_IP
        || contar_falhas('ip', $ip) >= LOGIN_MAX_POR_IP
        || contar_falhas('email', $email) >= LOGIN_MAX_POR_EMAIL;
}

function registrar_falha(string $email, string $ip): void {
    db()->prepare('INSERT INTO tentativas_login (email, ip) VALUES (?, ?)')->execute([$email, $ip]);
    if (random_int(1, 50) === 1) {   // limpeza ocasional, sem precisar de tarefa agendada
        db()->exec('DELETE FROM tentativas_login WHERE criada_em < NOW() - INTERVAL 1 DAY');
    }
}

// ---------- rotas ----------

function rota_me(): never {
    $u = usuario_atual();
    responder(200, [
        'usuario' => $u ? ['id' => (int)$u['id'], 'nome' => $u['nome'], 'email' => $u['email'], 'papel' => $u['papel']] : null,
        'plano' => $u ? plano_ativo((int)$u['id']) : null,
        'csrf' => csrf_token(),
    ]);
}

function rota_planos(): never {
    $linhas = db()->query('SELECT * FROM planos ORDER BY preco_mensal')->fetchAll();
    responder(200, array_map('plano_para_json', $linhas));
}

function rota_cadastro(): never {
    exigir_csrf();
    $c = corpo(8192);
    $nome = texto_limpo($c['nome'] ?? '', 120);
    $email = strtolower(texto_limpo($c['email'] ?? '', 190));
    $senha = is_string($c['senha'] ?? null) ? $c['senha'] : '';

    if ($nome === '') erro(400, 'Informe seu nome.');
    if ($email === '' || !filter_var($email, FILTER_VALIDATE_EMAIL)) erro(400, 'Informe um e-mail válido.');
    if (mb_strlen($senha) < 8) erro(400, 'A senha precisa ter pelo menos 8 caracteres.');
    if (strlen($senha) > 72) erro(400, 'A senha pode ter no máximo 72 caracteres.');   // limite do bcrypt

    try {
        $st = db()->prepare('INSERT INTO usuarios (nome, email, senha_hash) VALUES (?, ?, ?)');
        $st->execute([$nome, $email, password_hash($senha, PASSWORD_DEFAULT)]);
    } catch (PDOException $e) {
        if ((int)($e->errorInfo[1] ?? 0) === 1062) erro(409, 'Já existe uma conta com este e-mail.');
        throw $e;
    }
    entrar((int)db()->lastInsertId());
    $u = usuario_atual();
    responder(201, ['usuario' => ['id' => (int)$u['id'], 'nome' => $u['nome'], 'email' => $u['email'], 'papel' => $u['papel']], 'csrf' => csrf_token()]);
}

function rota_login(): never {
    exigir_csrf();
    $c = corpo(8192);
    $email = strtolower(texto_limpo($c['email'] ?? '', 190));
    $senha = is_string($c['senha'] ?? null) ? $c['senha'] : '';
    $ip = ip_do_cliente();

    if (login_bloqueado($email, $ip)) {
        header('Retry-After: 900');
        erro(429, 'Muitas tentativas. Aguarde alguns minutos e tente de novo.');
    }

    $st = db()->prepare('SELECT id, senha_hash FROM usuarios WHERE email = ?');
    $st->execute([$email]);
    $u = $st->fetch();
    // Mesmo sem conta, confere contra um hash de mentira: o tempo de resposta não revela se o e-mail existe.
    $hash = $u['senha_hash'] ?? '$2y$10$wmfh6exi9fNUeu5iUDh6ze0dF4x4fCYrYPelIRkz4W/TUVyFZ/vr.';
    $ok = password_verify($senha, $hash) && $u !== false;
    if (!$ok) {
        registrar_falha($email, $ip);
        erro(401, 'E-mail ou senha inválidos.');   // não diz qual dos dois falhou
    }
    db()->prepare('DELETE FROM tentativas_login WHERE email = ? AND ip = ?')->execute([$email, $ip]);
    entrar((int)$u['id']);
    $logado = usuario_atual();
    responder(200, [
        'usuario' => ['id' => (int)$logado['id'], 'nome' => $logado['nome'], 'email' => $logado['email'], 'papel' => $logado['papel']],
        'plano' => plano_ativo((int)$logado['id']),
        'csrf' => csrf_token(),
    ]);
}

function rota_logout(): never {
    exigir_csrf();
    $_SESSION = [];
    session_destroy();
    responder(200, ['ok' => true]);
}

/** Ativa um plano de demonstração. Sem pagamento, sem cartão (RF-07). */
function rota_assinatura(): never {
    $u = exigir_login();
    exigir_csrf();
    $c = corpo(1024);
    $planoId = $c['plano_id'] ?? null;
    if (!is_int($planoId) || $planoId <= 0) erro(400, 'Escolha um plano.');

    $st = db()->prepare('SELECT id FROM planos WHERE id = ?');
    $st->execute([$planoId]);
    if (!$st->fetch()) erro(404, 'Plano não encontrado.');

    $pdo = db();
    $pdo->beginTransaction();
    try {
        $pdo->prepare('UPDATE assinaturas SET status = "cancelada" WHERE usuario_id = ? AND status = "ativa"')->execute([$u['id']]);
        $pdo->prepare('INSERT INTO assinaturas (usuario_id, plano_id) VALUES (?, ?)')->execute([$u['id'], $planoId]);
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
    responder(201, ['plano' => plano_ativo((int)$u['id'])]);
}
