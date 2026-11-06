<?php
// Cria as tabelas, os planos de demonstração e, se pedido, o administrador. Roda no servidor, por SSH:
//   php ~/domains/hackathon.figueiredo.dev/setup.php admin@email "Nome" senha
// (fica ao lado do hackathon-config.php, fora do public_html)
// Pode rodar de novo: tabelas usam IF NOT EXISTS, os planos são atualizados e o admin é atualizado.

declare(strict_types=1);

if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }   // nunca pela web

require __DIR__ . '/hackathon-config.php';

$dsn = 'mysql:host=' . DB_HOST . (defined('DB_PORT') ? ';port=' . DB_PORT : '') . ';dbname=' . DB_NAME . ';charset=utf8mb4';
$pdo = new PDO($dsn, DB_USER, DB_PASS, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);

$tabelas = [
    'usuarios' => 'CREATE TABLE IF NOT EXISTS usuarios (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(120) NOT NULL,
        email VARCHAR(190) NOT NULL UNIQUE,
        senha_hash VARCHAR(255) NOT NULL,
        papel ENUM("admin","usuario") NOT NULL DEFAULT "usuario",
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',

    // Planos de demonstração: os valores são hipótese, não preço validado.
    'planos' => 'CREATE TABLE IF NOT EXISTS planos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(60) NOT NULL UNIQUE,
        preco_mensal DECIMAL(10,2) NOT NULL,
        franquia INT NOT NULL,
        preco_excedente DECIMAL(10,2) NOT NULL,
        tenants JSON NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',

    'assinaturas' => 'CREATE TABLE IF NOT EXISTS assinaturas (
        id INT AUTO_INCREMENT PRIMARY KEY,
        usuario_id INT NOT NULL,
        plano_id INT NOT NULL,
        status ENUM("ativa","cancelada") NOT NULL DEFAULT "ativa",
        criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX (usuario_id, status),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
        FOREIGN KEY (plano_id) REFERENCES planos(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',

    'telefones' => 'CREATE TABLE IF NOT EXISTS telefones (
        id INT AUTO_INCREMENT PRIMARY KEY,
        usuario_id INT NOT NULL,
        numero VARCHAR(20) NOT NULL UNIQUE,
        status ENUM("pendente","aprovado","revogado") NOT NULL DEFAULT "pendente",
        aprovado_por INT NULL,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX (usuario_id),
        INDEX (status),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
        FOREIGN KEY (aprovado_por) REFERENCES usuarios(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',

    // A fila: o notebook busca a pergunta mais antiga e devolve os eventos. Os entes são copiados do plano
    // no momento da pergunta, então mudar de plano depois não altera uma consulta em andamento.
    'perguntas' => 'CREATE TABLE IF NOT EXISTS perguntas (
        id INT AUTO_INCREMENT PRIMARY KEY,
        usuario_id INT NOT NULL,
        plano_id INT NOT NULL,
        texto VARCHAR(500) NOT NULL,
        tenants JSON NOT NULL,
        status ENUM("fila","processando","concluida","erro") NOT NULL DEFAULT "fila",
        criada_em DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        iniciada_em DATETIME(3) NULL,
        concluida_em DATETIME(3) NULL,
        duracao_ms INT NULL,
        INDEX (status, id),
        INDEX (usuario_id, status),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
        FOREIGN KEY (plano_id) REFERENCES planos(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',

    'eventos' => 'CREATE TABLE IF NOT EXISTS eventos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        pergunta_id INT NOT NULL,
        seq INT NOT NULL,
        tipo ENUM("consulta","texto","fonte","fim","erro") NOT NULL,
        dados JSON NULL,
        criado_em DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        UNIQUE KEY pergunta_seq (pergunta_id, seq),
        FOREIGN KEY (pergunta_id) REFERENCES perguntas(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',

    // Só falhas: serve para limitar tentativas de login.
    'tentativas_login' => 'CREATE TABLE IF NOT EXISTS tentativas_login (
        id INT AUTO_INCREMENT PRIMARY KEY,
        email VARCHAR(190) NOT NULL,
        ip VARCHAR(45) NOT NULL,
        criada_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX (email, ip, criada_em),
        INDEX (ip, criada_em)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
];
foreach ($tabelas as $nome => $sql) {
    $pdo->exec($sql);
}

$planos = [
    ['Município', 990.00, 300, 1.50, ['pe-garanhuns']],
    ['Estado', 1990.00, 1000, 1.50, ['pe-estado', 'pe-garanhuns']],
];
$st = $pdo->prepare('INSERT INTO planos (nome, preco_mensal, franquia, preco_excedente, tenants) VALUES (?, ?, ?, ?, ?)
                     ON DUPLICATE KEY UPDATE preco_mensal = VALUES(preco_mensal), franquia = VALUES(franquia),
                     preco_excedente = VALUES(preco_excedente), tenants = VALUES(tenants)');
foreach ($planos as [$nome, $preco, $franquia, $excedente, $tenants]) {
    $st->execute([$nome, $preco, $franquia, $excedente, json_encode($tenants)]);
}

[$_, $email, $nome, $senha] = $argv + [null, null, null, null];
if ($email && $senha) {
    $st = $pdo->prepare('INSERT INTO usuarios (nome, email, senha_hash, papel) VALUES (?, ?, ?, "admin")
                         ON DUPLICATE KEY UPDATE nome = VALUES(nome), senha_hash = VALUES(senha_hash), papel = "admin"');
    $st->execute([$nome ?: 'Admin', strtolower($email), password_hash($senha, PASSWORD_DEFAULT)]);
    echo "admin pronto: $email\n";
}
echo 'tabelas ok (' . count($tabelas) . '), planos: ' . count($planos) . "\n";
