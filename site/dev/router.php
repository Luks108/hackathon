<?php
// Roteador do servidor embutido do PHP, só para desenvolvimento. Faz o papel do .htaccess:
//   php -S 127.0.0.1:8080 -t site/public_html site/dev/router.php
// Em produção quem manda /api/* para api/index.php é o site/public_html/.htaccess.

$caminho = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?? '/';

if (preg_match('#^/api(/|$)#', $caminho)) {
    require __DIR__ . '/../public_html/api/index.php';
    return true;
}
return false;   // o resto é arquivo estático
