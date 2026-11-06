<?php
// Telefones do WhatsApp: o usuário cadastra e remove (A08); só o administrador aprova ou revoga (A09).
// O número começa "pendente". O worker só enxerga os "aprovados" cujo dono tem plano ativo (GET /api/worker/telefones).

declare(strict_types=1);
if (!defined('API')) { http_response_code(404); exit; }

const TELEFONES_POR_CONTA = 3;
const TELEFONE_STATUS = ['pendente', 'aprovado', 'revogado'];

/**
 * Devolve o celular brasileiro no formato canônico (55 + DDD + 9 + 8 dígitos, 13 dígitos), ou null se não for um.
 * Aceita "(87) 99999-9999", "+55 87 99999-9999", "87999999999", "0 87 99999-9999" e o celular antigo sem o 9.
 * O formato único evita cadastrar a mesma pessoa duas vezes com formas diferentes de escrever o número.
 */
function normalizar_telefone(mixed $bruto): ?string {
    if (!is_string($bruto) || strlen($bruto) > 40) return null;
    // Só o que se digita num telefone: dígitos, espaço, parênteses, hífen, ponto e +. Qualquer outro caractere
    // (letra, aspa, texto junto do número) recusa a entrada em vez de ser descartado em silêncio.
    if (!preg_match('/^[\d\s().+\-]+$/D', $bruto)) return null;
    $d = preg_replace('/\D+/', '', $bruto);
    if ($d === null || $d === '') return null;
    if (str_starts_with($d, '00')) $d = substr($d, 2);         // prefixo internacional: 0055...
    elseif (str_starts_with($d, '0')) $d = substr($d, 1);      // prefixo de operadora ou tronco: 087...
    if (strlen($d) <= 11) $d = '55' . $d;                      // sem o código do país
    if (!str_starts_with($d, '55')) return null;
    $local = substr($d, 2);                                    // DDD + número
    if (!in_array(strlen($local), [10, 11], true)) return null;
    $ddd = substr($local, 0, 2);
    $numero = substr($local, 2);
    if (!preg_match('/^[1-9][1-9]$/', $ddd)) return null;
    if (strlen($numero) === 8) {
        if (!preg_match('/^[6-9]/', $numero)) return null;     // fixo: não tem WhatsApp
        $numero = '9' . $numero;                               // celular antigo: acrescenta o 9
    } elseif ($numero[0] !== '9') {
        return null;
    }
    return '55' . $ddd . $numero;
}

function telefone_do_usuario_json(array $t): array {
    return ['id' => (int)$t['id'], 'numero' => $t['numero'], 'status' => $t['status'], 'criado_em' => $t['criado_em']];
}

// ---------- A08: o usuário ----------

function rota_telefones_listar(): never {
    $u = exigir_login();
    $st = db()->prepare('SELECT id, numero, status, criado_em FROM telefones WHERE usuario_id = ? ORDER BY id');
    $st->execute([$u['id']]);
    responder(200, array_map('telefone_do_usuario_json', $st->fetchAll()));
}

function rota_telefones_criar(): never {
    $u = exigir_login();
    exigir_csrf();
    $c = corpo(1024);
    $numero = normalizar_telefone($c['numero'] ?? null);
    if ($numero === null) erro(400, 'Informe um celular brasileiro com DDD, como (87) 99999-9999.');
    if (plano_ativo((int)$u['id']) === null) erro(403, 'Ative um plano para cadastrar um telefone.');

    $pdo = db();
    $pdo->beginTransaction();
    try {
        // Trava a conta: seis requisições ao mesmo tempo não furam o limite.
        $pdo->prepare('SELECT id FROM usuarios WHERE id = ? FOR UPDATE')->execute([$u['id']]);
        $st = $pdo->prepare('SELECT COUNT(*) FROM telefones WHERE usuario_id = ?');
        $st->execute([$u['id']]);
        if ((int)$st->fetchColumn() >= TELEFONES_POR_CONTA) {
            $pdo->rollBack();
            erro(400, 'Cada conta pode ter até ' . TELEFONES_POR_CONTA . ' telefones. Remova um para cadastrar outro.');
        }
        $pdo->prepare('INSERT INTO telefones (usuario_id, numero) VALUES (?, ?)')->execute([$u['id'], $numero]);
        $id = (int)$pdo->lastInsertId();
        $pdo->commit();
    } catch (PDOException $e) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        // Mesma resposta para "é seu" e "é de outra conta": não revela quem cadastrou o número.
        if ((int)($e->errorInfo[1] ?? 0) === 1062) erro(409, 'Este número já está cadastrado.');
        throw $e;
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        throw $e;
    }
    responder(201, ['id' => $id, 'numero' => $numero, 'status' => 'pendente']);
}

function rota_telefones_remover(int $id): never {
    $u = exigir_login();
    exigir_csrf();
    $st = db()->prepare('DELETE FROM telefones WHERE id = ? AND usuario_id = ?');
    $st->execute([$id, $u['id']]);
    if ($st->rowCount() === 0) erro(404, 'Telefone não encontrado.');   // inexistente ou de outra conta: mesma resposta
    responder(204);
}

// ---------- A09: o administrador ----------

const ADMIN_TELEFONE_SQL = 'SELECT t.id, t.numero, t.status, t.criado_em, t.atualizado_em,
        u.id AS usuario_id, u.nome AS usuario_nome, u.email AS usuario_email,
        (SELECT p.nome FROM assinaturas a JOIN planos p ON p.id = a.plano_id
          WHERE a.usuario_id = u.id AND a.status = "ativa" ORDER BY a.id DESC LIMIT 1) AS plano,
        d.id AS decidido_por_id, d.nome AS decidido_por_nome, d.email AS decidido_por_email
    FROM telefones t
    JOIN usuarios u ON u.id = t.usuario_id
    LEFT JOIN usuarios d ON d.id = t.aprovado_por';

function telefone_admin_json(array $t): array {
    return [
        'id' => (int)$t['id'],
        'numero' => $t['numero'],
        'status' => $t['status'],
        'criado_em' => $t['criado_em'],
        'atualizado_em' => $t['atualizado_em'],
        'usuario' => ['id' => (int)$t['usuario_id'], 'nome' => $t['usuario_nome'], 'email' => $t['usuario_email'], 'plano' => $t['plano']],
        // Quem tomou a última decisão (aprovar ou revogar). Nulo enquanto está pendente.
        'decidido_por' => $t['decidido_por_id'] === null ? null : ['id' => (int)$t['decidido_por_id'], 'nome' => $t['decidido_por_nome'], 'email' => $t['decidido_por_email']],
    ];
}

function rota_admin_telefones(): never {
    exigir_admin();
    $status = $_GET['status'] ?? 'pendente';
    if (!is_string($status) || ($status !== 'todos' && !in_array($status, TELEFONE_STATUS, true))) {
        erro(400, 'O status precisa ser pendente, aprovado, revogado ou todos.');
    }
    $sql = ADMIN_TELEFONE_SQL . ($status === 'todos' ? '' : ' WHERE t.status = ?') . ' ORDER BY t.id LIMIT 200';
    $st = db()->prepare($sql);
    $st->execute($status === 'todos' ? [] : [$status]);
    responder(200, array_map('telefone_admin_json', $st->fetchAll()));
}

/** Aprova ou revoga. Repetir a mesma decisão é inofensivo e não troca quem decidiu primeiro. */
function decidir_telefone(int $id, string $novoStatus): never {
    $admin = exigir_admin();
    exigir_csrf();
    $pdo = db();
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare('SELECT status FROM telefones WHERE id = ? FOR UPDATE');
        $st->execute([$id]);
        $atual = $st->fetchColumn();
        if ($atual === false) { $pdo->rollBack(); erro(404, 'Telefone não encontrado.'); }
        if ($atual !== $novoStatus) {
            $pdo->prepare('UPDATE telefones SET status = ?, aprovado_por = ? WHERE id = ?')->execute([$novoStatus, $admin['id'], $id]);
        }
        $pdo->commit();
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        throw $e;
    }
    $st = $pdo->prepare(ADMIN_TELEFONE_SQL . ' WHERE t.id = ?');
    $st->execute([$id]);
    responder(200, telefone_admin_json($st->fetch()));
}

function rota_admin_aprovar(int $id): never { decidir_telefone($id, 'aprovado'); }
function rota_admin_revogar(int $id): never { decidir_telefone($id, 'revogado'); }
