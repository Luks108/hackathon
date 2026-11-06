<?php
// API do hackathon — PHP puro + MySQL, sem framework, para adaptar ao desafio em minutos.
//
// Autenticação:
//   pessoas   → sessão (POST /api/login), cookie HttpOnly
//   máquinas  → header X-Api-Key (notebook de inferência, canal WhatsApp)
//
// Rotas:
//   POST /api/login            {email, senha}
//   POST /api/logout
//   GET  /api/me
//   GET  /api/registros
//   POST /api/registros        multipart: titulo, descricao, foto  (ou JSON sem foto)
//   PATCH /api/registros/{id}  {analise}            ← o notebook devolve o resultado da IA aqui
//   GET  /api/saude

declare(strict_types=1);
require dirname(__DIR__, 2) . '/hackathon-config.php'; // fora do public_html

header('Content-Type: application/json; charset=utf-8');
session_set_cookie_params(['httponly' => true, 'secure' => true, 'samesite' => 'Lax']);
session_start();

function db(): PDO {
    static $pdo;
    return $pdo ??= new PDO('mysql:host=' . DB_HOST . ';dbname=' . DB_NAME . ';charset=utf8mb4', DB_USER, DB_PASS, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
}

function responder(int $status, $dados): never {
    http_response_code($status);
    echo json_encode($dados, JSON_UNESCAPED_UNICODE);
    exit;
}

function corpo(): array {
    if (!str_contains($_SERVER['CONTENT_TYPE'] ?? '', 'application/json')) return $_POST;
    $j = json_decode(file_get_contents('php://input') ?: '[]', true);
    return is_array($j) ? $j : [];
}

/** Usuário da sessão, ou a "máquina" se a chave de API bater. */
function autenticado(): array {
    $chave = $_SERVER['HTTP_X_API_KEY'] ?? '';
    if ($chave !== '' && hash_equals(API_KEY, $chave)) return ['id' => null, 'nome' => 'máquina', 'papel' => 'maquina'];
    if (!empty($_SESSION['usuario'])) return $_SESSION['usuario'];
    responder(401, ['erro' => 'faça login']);
}

/** Envia a foto ao notebook de inferência (YOLO). Se estiver offline, segue sem análise. */
function inferir(string $caminho): ?array {
    if (!defined('INFERENCIA_URL') || INFERENCIA_URL === '') return null;
    $ch = curl_init(rtrim(INFERENCIA_URL, '/') . '/detectar');
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => ['imagem' => new CURLFile($caminho)],
        CURLOPT_HTTPHEADER => ['X-Api-Key: ' . API_KEY],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
    ]);
    $r = curl_exec($ch);
    $ok = curl_getinfo($ch, CURLINFO_HTTP_CODE) === 200;
    curl_close($ch);
    return $ok ? json_decode((string)$r, true) : null;
}

$metodo = $_SERVER['REQUEST_METHOD'];
$rota = trim(preg_replace('#^/api#', '', parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH)), '/');

try {
    if ($rota === 'saude') responder(200, ['ok' => true, 'hora' => date('c')]);

    if ($rota === 'login' && $metodo === 'POST') {
        $c = corpo();
        $st = db()->prepare('SELECT id, nome, email, papel, senha_hash FROM usuarios WHERE email = ?');
        $st->execute([strtolower(trim($c['email'] ?? ''))]);
        $u = $st->fetch();
        if (!$u || !password_verify((string)($c['senha'] ?? ''), $u['senha_hash'])) responder(401, ['erro' => 'e-mail ou senha inválidos']);
        unset($u['senha_hash']);
        session_regenerate_id(true);
        $_SESSION['usuario'] = $u;
        responder(200, $u);
    }

    if ($rota === 'logout') { session_destroy(); responder(200, ['ok' => true]); }

    if ($rota === 'me') responder(200, autenticado());

    if ($rota === 'registros' && $metodo === 'GET') {
        autenticado();
        $linhas = db()->query('SELECT r.*, u.nome AS autor FROM registros r LEFT JOIN usuarios u ON u.id = r.usuario_id ORDER BY r.id DESC LIMIT 200')->fetchAll();
        foreach ($linhas as &$l) $l['analise'] = $l['analise'] ? json_decode($l['analise'], true) : null;
        responder(200, $linhas);
    }

    if ($rota === 'registros' && $metodo === 'POST') {
        $u = autenticado();
        $c = corpo();
        $foto = null;
        $analise = null;
        if (!empty($_FILES['foto']['tmp_name'])) {
            $tipo = mime_content_type($_FILES['foto']['tmp_name']);
            $ext = ['image/jpeg' => 'jpg', 'image/png' => 'png', 'image/webp' => 'webp'][$tipo] ?? null;
            if (!$ext) responder(400, ['erro' => "tipo de imagem não aceito: $tipo"]);
            $nome = date('Ymd-His') . '-' . bin2hex(random_bytes(4)) . ".$ext";
            $destino = dirname(__DIR__) . "/uploads/$nome";
            move_uploaded_file($_FILES['foto']['tmp_name'], $destino);
            $foto = "uploads/$nome";
            $analise = inferir($destino);
        }
        $st = db()->prepare('INSERT INTO registros (usuario_id, titulo, descricao, foto, analise, origem) VALUES (?, ?, ?, ?, ?, ?)');
        $st->execute([$u['id'], $c['titulo'] ?? '', $c['descricao'] ?? '', $foto, $analise ? json_encode($analise, JSON_UNESCAPED_UNICODE) : null, $c['origem'] ?? 'web']);
        responder(201, ['id' => (int)db()->lastInsertId(), 'foto' => $foto, 'analise' => $analise]);
    }

    if (preg_match('#^registros/(\d+)$#', $rota, $m) && $metodo === 'PATCH') {
        autenticado();
        $c = corpo();
        $st = db()->prepare('UPDATE registros SET analise = ? WHERE id = ?');
        $st->execute([json_encode($c['analise'] ?? null, JSON_UNESCAPED_UNICODE), (int)$m[1]]);
        responder(200, ['ok' => true]);
    }

    responder(404, ['erro' => "rota não encontrada: $metodo /api/$rota"]);
} catch (Throwable $e) {
    error_log('[api] ' . $e->getMessage());
    responder(500, ['erro' => 'erro interno']);
}
