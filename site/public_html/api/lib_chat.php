<?php
// Chat: o navegador cria a pergunta e lê os eventos. Quem responde é o worker, no notebook (lib_worker.php).

declare(strict_types=1);
if (!defined('API')) { http_response_code(404); exit; }

const PERGUNTA_MAX_CARACTERES = 500;
const FILA_MAX_SEGUNDOS = 120;         // ninguém pegou a pergunta: o notebook está fora do ar
const PROCESSANDO_MAX_SEGUNDOS = 180;  // pegaram, mas não terminaram

/**
 * Encerra com erro as perguntas que passaram do limite. Roda nas rotas que o navegador e o worker já chamam,
 * então não depende de tarefa agendada, e o navegador sempre recebe uma mensagem em vez de esperar para sempre.
 */
function fechar_vencidas(): void {
    $regras = [
        ['fila', 'criada_em', FILA_MAX_SEGUNDOS, 'O serviço de consulta está indisponível no momento. Tente novamente em instantes.'],
        ['processando', 'iniciada_em', PROCESSANDO_MAX_SEGUNDOS, 'A consulta demorou mais que o esperado. Tente novamente.'],
    ];
    foreach ($regras as [$status, $coluna, $segundos, $motivo]) {
        $st = db()->prepare("SELECT id FROM perguntas WHERE status = ? AND $coluna < NOW(3) - INTERVAL " . (int)$segundos . ' SECOND');
        $st->execute([$status]);
        foreach ($st->fetchAll(PDO::FETCH_COLUMN) as $id) {
            encerrar_com_erro((int)$id, $status, $motivo);
        }
    }
}

function encerrar_com_erro(int $id, string $statusEsperado, string $motivo): void {
    $pdo = db();
    $pdo->beginTransaction();
    try {
        // Trava a linha: o worker também a trava ao gravar eventos, então um não atropela o outro.
        $st = $pdo->prepare('SELECT status FROM perguntas WHERE id = ? FOR UPDATE');
        $st->execute([$id]);
        if ($st->fetchColumn() !== $statusEsperado) { $pdo->commit(); return; }   // mudou enquanto olhávamos
        $pdo->prepare('UPDATE perguntas SET status = "erro", concluida_em = NOW(3),
                       duracao_ms = TIMESTAMPDIFF(MICROSECOND, COALESCE(iniciada_em, criada_em), NOW(3)) DIV 1000 WHERE id = ?')->execute([$id]);
        $pdo->prepare('INSERT INTO eventos (pergunta_id, seq, tipo, dados)
                       SELECT ?, COALESCE(MAX(seq), 0) + 1, "erro", ? FROM eventos WHERE pergunta_id = ?')
            ->execute([$id, json_encode(['motivo' => $motivo], JSON_UNESCAPED_UNICODE), $id]);
        $pdo->commit();
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        error_log('[api] não consegui encerrar a pergunta ' . $id . ': ' . $e->getMessage());
    }
}

function pergunta_aberta_do_usuario(int $usuarioId): ?array {
    $st = db()->prepare('SELECT id, texto, status FROM perguntas WHERE usuario_id = ? AND status IN ("fila","processando") ORDER BY id DESC LIMIT 1');
    $st->execute([$usuarioId]);
    return $st->fetch() ?: null;
}

// ---------- rotas ----------

function rota_perguntas_criar(): never {
    $u = exigir_login();
    exigir_csrf();
    $c = corpo(4096);

    $texto = is_string($c['texto'] ?? null) ? trim($c['texto']) : '';
    if ($texto === '') erro(400, 'Escreva sua pergunta.');
    if (mb_strlen($texto) > PERGUNTA_MAX_CARACTERES) erro(400, 'A pergunta pode ter no máximo ' . PERGUNTA_MAX_CARACTERES . ' caracteres.');
    $texto = texto_limpo($texto, PERGUNTA_MAX_CARACTERES);
    if ($texto === '') erro(400, 'Escreva sua pergunta.');

    $plano = plano_ativo((int)$u['id']);
    if ($plano === null) erro(403, 'Ative um plano para fazer perguntas.');

    fechar_vencidas();

    $pdo = db();
    $pdo->beginTransaction();
    try {
        // Trava o usuário: duas requisições ao mesmo tempo não conseguem abrir duas perguntas.
        $pdo->prepare('SELECT id FROM usuarios WHERE id = ? FOR UPDATE')->execute([$u['id']]);
        $aberta = pergunta_aberta_do_usuario((int)$u['id']);
        if ($aberta !== null) {
            $pdo->rollBack();
            responder(409, ['erro' => 'Você já tem uma pergunta em andamento. Aguarde a resposta.', 'pergunta_id' => (int)$aberta['id']]);
        }
        // Os entes são copiados do plano agora: mudar de plano depois não altera a consulta em andamento.
        $pdo->prepare('INSERT INTO perguntas (usuario_id, plano_id, texto, tenants) VALUES (?, ?, ?, ?)')
            ->execute([$u['id'], $plano['id'], $texto, json_encode($plano['tenants'])]);
        $id = (int)$pdo->lastInsertId();
        $pdo->commit();
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        throw $e;
    }
    responder(201, ['id' => $id]);
}

/** Pergunta em andamento do usuário, para a tela voltar a acompanhá-la depois de recarregar. */
function rota_pergunta_aberta(): never {
    $u = exigir_login();
    fechar_vencidas();
    $a = pergunta_aberta_do_usuario((int)$u['id']);
    responder(200, ['pergunta' => $a ? ['id' => (int)$a['id'], 'texto' => $a['texto'], 'status' => $a['status']] : null]);
}

function rota_eventos(int $id): never {
    $u = exigir_login();
    fechar_vencidas();

    $desde = filter_var($_GET['desde'] ?? 0, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0]]);
    if ($desde === false) erro(400, 'O parâmetro "desde" precisa ser um número inteiro.');

    // Só o dono lê. Para qualquer outro, a pergunta "não existe" (404), sem confirmar que existe.
    $st = db()->prepare('SELECT status, duracao_ms FROM perguntas WHERE id = ? AND usuario_id = ?');
    $st->execute([$id, $u['id']]);
    $p = $st->fetch();
    if (!$p) erro(404, 'Pergunta não encontrada.');

    // O status é lido antes dos eventos: se já terminou, todos os eventos já foram gravados.
    $st = db()->prepare('SELECT seq, tipo, dados FROM eventos WHERE pergunta_id = ? AND seq > ? ORDER BY seq LIMIT 200');
    $st->execute([$id, $desde]);
    $eventos = array_map(fn($e) => [
        'seq' => (int)$e['seq'],
        'tipo' => $e['tipo'],
        'dados' => $e['dados'] === null ? null : json_decode((string)$e['dados'], true),
    ], $st->fetchAll());

    responder(200, ['status' => $p['status'], 'duracao_ms' => $p['duracao_ms'] === null ? null : (int)$p['duracao_ms'], 'eventos' => $eventos]);
}
