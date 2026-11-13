<?php
// Rotas do worker (o notebook). Só conexões de saída: o notebook busca trabalho e devolve o resultado.
// Todas exigem X-Worker-Key. Não usam sessão nem cookie.

declare(strict_types=1);
if (!defined('API')) { http_response_code(404); exit; }

const EVENTOS_TIPOS = ['consulta', 'texto', 'fonte', 'fim', 'erro'];
const EVENTOS_POR_LOTE = 100;
const EVENTO_MAX_BYTES = 20000;

function exigir_worker(): void {
    if (!defined('WORKER_KEY') || !is_string(WORKER_KEY) || strlen(WORKER_KEY) < 24) {
        erro(503, 'Worker desativado: configure WORKER_KEY com pelo menos 24 caracteres.');
    }
    $enviada = $_SERVER['HTTP_X_WORKER_KEY'] ?? '';
    if (!is_string($enviada) || $enviada === '' || !hash_equals(WORKER_KEY, $enviada)) {
        erro(401, 'Chave do worker inválida.');
    }
}

/** Reserva a pergunta mais antiga da fila. Dois workers nunca recebem a mesma. */
function rota_worker_proxima(): never {
    exigir_worker();
    fechar_vencidas();
    $pdo = db();
    for ($tentativa = 0; $tentativa < 5; $tentativa++) {
        $id = $pdo->query('SELECT id FROM perguntas WHERE status = "fila" ORDER BY id LIMIT 1')->fetchColumn();
        if ($id === false) responder(204);
        // A reserva é um UPDATE condicional: só um dos concorrentes consegue mudar a linha de "fila" para "processando".
        $up = $pdo->prepare('UPDATE perguntas SET status = "processando", iniciada_em = NOW(3) WHERE id = ? AND status = "fila"');
        $up->execute([$id]);
        if ($up->rowCount() === 1) {
            // espera_ms: quanto a pergunta ficou na fila (criada_em até a reserva acima). Calculada pelo banco, com o mesmo relógio
            // dos dois horários, para não depender do fuso nem do relógio do notebook. Só entra no log do worker.
            $st = $pdo->prepare('SELECT id, usuario_id, plano_id, texto, tenants,
                                        TIMESTAMPDIFF(MICROSECOND, criada_em, iniciada_em) DIV 1000 AS espera_ms
                                 FROM perguntas WHERE id = ?');
            $st->execute([$id]);
            $p = $st->fetch();
            responder(200, [
                'id' => (int)$p['id'],
                'usuario_id' => (int)$p['usuario_id'],
                'plano_id' => (int)$p['plano_id'],
                'texto' => $p['texto'],
                'tenants' => json_decode((string)$p['tenants'], true) ?: [],
                'ver_pessoal' => false,   // nenhum plano de demonstração enxerga pessoa física
                'espera_ms' => max(0, (int)$p['espera_ms']),
            ]);
        }
        // outro worker foi mais rápido: tenta a próxima
    }
    responder(204);
}

/** Grava um lote de eventos. Repetir um seq é seguro: o repetido é ignorado. */
function rota_worker_eventos(int $id): never {
    exigir_worker();
    $c = corpo(1048576);
    $lista = $c['eventos'] ?? null;
    if (!is_array($lista) || $lista === [] || count($lista) > EVENTOS_POR_LOTE) {
        erro(400, 'Envie de 1 a ' . EVENTOS_POR_LOTE . ' eventos.');
    }
    $limpos = [];
    foreach ($lista as $e) {
        if (!is_array($e) || !is_int($e['seq'] ?? null) || $e['seq'] < 1 || !in_array($e['tipo'] ?? null, EVENTOS_TIPOS, true)) {
            erro(400, 'Cada evento precisa de seq (inteiro maior que zero) e tipo (' . implode(', ', EVENTOS_TIPOS) . ').');
        }
        $dados = $e['dados'] ?? null;
        if ($dados !== null && !is_array($dados)) erro(400, '"dados" precisa ser um objeto.');
        $json = $dados === null ? null : json_encode($dados, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($json !== null && strlen($json) > EVENTO_MAX_BYTES) erro(413, 'Um evento passou de ' . EVENTO_MAX_BYTES . ' bytes.');
        $limpos[] = [$e['seq'], $e['tipo'], $json];
    }

    $pdo = db();
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare('SELECT status FROM perguntas WHERE id = ? FOR UPDATE');
        $st->execute([$id]);
        $status = $st->fetchColumn();
        if ($status === false) { $pdo->rollBack(); erro(404, 'Pergunta não encontrada.'); }

        if ($status !== 'processando') {
            // Pergunta encerrada. Reenviar um lote que já foi gravado é inofensivo; eventos novos não são aceitos.
            $seqs = array_column($limpos, 0);
            $marcas = implode(',', array_fill(0, count($seqs), '?'));
            $ex = $pdo->prepare("SELECT COUNT(*) FROM eventos WHERE pergunta_id = ? AND seq IN ($marcas)");
            $ex->execute([$id, ...$seqs]);
            $jaGravados = (int)$ex->fetchColumn();
            $pdo->commit();
            if ($jaGravados === count(array_unique($seqs))) responder(200, ['gravados' => 0, 'ignorados' => count($limpos), 'status' => $status]);
            erro(409, 'Esta pergunta já foi encerrada.');
        }

        $ins = $pdo->prepare('INSERT IGNORE INTO eventos (pergunta_id, seq, tipo, dados) VALUES (?, ?, ?, ?)');
        $gravados = 0;
        $final = null;
        foreach ($limpos as [$seq, $tipo, $json]) {
            $ins->execute([$id, $seq, $tipo, $json]);
            if ($ins->rowCount() === 1) {
                $gravados++;
                if ($tipo === 'fim') $final = 'concluida';
                if ($tipo === 'erro') $final = 'erro';
            }
        }
        if ($final !== null) {
            $pdo->prepare('UPDATE perguntas SET status = ?, concluida_em = NOW(3),
                           duracao_ms = TIMESTAMPDIFF(MICROSECOND, iniciada_em, NOW(3)) DIV 1000 WHERE id = ? AND status = "processando"')
                ->execute([$final, $id]);
        }
        $pdo->commit();
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        throw $e;
    }
    responder(200, ['gravados' => $gravados, 'ignorados' => count($limpos) - $gravados, 'status' => $final ?? 'processando']);
}

/** Telefones aprovados e os entes do plano de cada dono. Quem perdeu o plano deixa de aparecer. */
function rota_worker_telefones(): never {
    exigir_worker();
    $linhas = db()->query('SELECT t.numero, p.tenants FROM telefones t
        JOIN assinaturas a ON a.usuario_id = t.usuario_id AND a.status = "ativa"
        JOIN planos p ON p.id = a.plano_id
        WHERE t.status = "aprovado" ORDER BY t.id')->fetchAll();
    responder(200, array_map(fn($l) => ['numero' => $l['numero'], 'tenants' => json_decode((string)$l['tenants'], true) ?: []], $linhas));
}
