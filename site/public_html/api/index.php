<?php
// API do site: PHP puro + MySQL, sem framework. O contrato está em docs/specs/001-site-e-chat/plan.md.
//
// Navegador (sessão em cookie HttpOnly; escrita exige o cabeçalho X-CSRF-Token, que vem de GET /api/me):
//   GET  /api/saude
//   GET  /api/me                          usuário, plano e token CSRF
//   GET  /api/planos
//   POST /api/cadastro  /api/login  /api/logout
//   POST /api/assinatura                  {plano_id}: ativa um plano de demonstração
//   POST /api/perguntas                   {texto}
//   GET  /api/perguntas/aberta
//   GET  /api/perguntas/{id}/eventos?desde=N
//   GET  /api/telefones                   os telefones do usuário
//   POST /api/telefones                   {numero}: nasce "pendente"
//   DELETE /api/telefones/{id}
//
// Administrador (papel "admin"):
//   GET  /api/admin/telefones?status=pendente|aprovado|revogado|todos
//   POST /api/admin/telefones/{id}/aprovar  e  /revogar
//
// Worker (cabeçalho X-Worker-Key, sem sessão):
//   POST /api/worker/proxima
//   POST /api/worker/perguntas/{id}/eventos
//   GET  /api/worker/telefones

declare(strict_types=1);
define('API', true);

require dirname(__DIR__, 2) . '/hackathon-config.php';   // fora do public_html
foreach (['base', 'conta', 'chat', 'telefones', 'worker'] as $modulo) {
    require __DIR__ . "/lib_$modulo.php";
}

header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

// [método, padrão, usa sessão, função]. Os ids capturados chegam como inteiros.
$rotas = [
    ['GET',  '#^saude$#',                          false, function () {
        db()->query('SELECT 1');
        responder(200, ['ok' => true, 'hora' => date('c')]);
    }],
    ['GET',  '#^me$#',                             true,  'rota_me'],
    ['GET',  '#^planos$#',                         true,  'rota_planos'],
    ['POST', '#^cadastro$#',                       true,  'rota_cadastro'],
    ['POST', '#^login$#',                          true,  'rota_login'],
    ['POST', '#^logout$#',                         true,  'rota_logout'],
    ['POST', '#^assinatura$#',                     true,  'rota_assinatura'],
    ['POST', '#^perguntas$#',                      true,  'rota_perguntas_criar'],
    ['GET',  '#^perguntas/aberta$#',               true,  'rota_pergunta_aberta'],
    ['GET',    '#^telefones$#',                       true,  'rota_telefones_listar'],
    ['POST',   '#^telefones$#',                       true,  'rota_telefones_criar'],
    ['DELETE', '#^telefones/(\d+)$#',                 true,  'rota_telefones_remover'],
    ['GET',    '#^admin/telefones$#',                 true,  'rota_admin_telefones'],
    ['POST',   '#^admin/telefones/(\d+)/aprovar$#',   true,  'rota_admin_aprovar'],
    ['POST',   '#^admin/telefones/(\d+)/revogar$#',   true,  'rota_admin_revogar'],
    ['GET',  '#^perguntas/(\d+)/eventos$#',        true,  'rota_eventos'],
    ['POST', '#^worker/proxima$#',                 false, 'rota_worker_proxima'],
    ['POST', '#^worker/perguntas/(\d+)/eventos$#', false, 'rota_worker_eventos'],
    ['GET',  '#^worker/telefones$#',               false, 'rota_worker_telefones'],
];

$metodo = $_SERVER['REQUEST_METHOD'];
$rota = trim((string)preg_replace('#^/api#', '', (string)parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH)), '/');

try {
    $existe = false;
    foreach ($rotas as [$m, $padrao, $usaSessao, $funcao]) {
        if (!preg_match($padrao, $rota, $g)) continue;
        $existe = true;
        if ($m !== $metodo) continue;
        if ($usaSessao) iniciar_sessao();
        $funcao(...array_map('intval', array_slice($g, 1)));
    }
    erro($existe ? 405 : 404, $existe ? 'Método não permitido.' : 'Rota não encontrada.');
} catch (Throwable $e) {
    error_log('[api] ' . $e::class . ': ' . $e->getMessage() . ' em ' . $e->getFile() . ':' . $e->getLine());
    erro(500, 'Erro interno. Tente novamente em instantes.');
}
