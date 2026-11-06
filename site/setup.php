<?php
// Cria as tabelas e o usuário admin. Roda no servidor, por SSH:
//   php ~/domains/hackathon.figueiredo.dev/setup.php admin@email "Nome" senha
// (fica ao lado do hackathon-config.php, fora do public_html)
// Pode rodar de novo: tabelas usam IF NOT EXISTS e o admin é atualizado.

declare(strict_types=1);
require __DIR__ . '/hackathon-config.php';

$pdo = new PDO('mysql:host=' . DB_HOST . ';dbname=' . DB_NAME . ';charset=utf8mb4', DB_USER, DB_PASS, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);

$pdo->exec('CREATE TABLE IF NOT EXISTS usuarios (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL UNIQUE,
  senha_hash VARCHAR(255) NOT NULL,
  papel ENUM("admin","usuario") NOT NULL DEFAULT "usuario",
  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4');

$pdo->exec('CREATE TABLE IF NOT EXISTS registros (
  id INT AUTO_INCREMENT PRIMARY KEY,
  usuario_id INT NULL,
  titulo VARCHAR(200) NOT NULL DEFAULT "",
  descricao TEXT,
  foto VARCHAR(255) NULL,
  analise JSON NULL,
  origem VARCHAR(30) NOT NULL DEFAULT "web",
  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4');

[$_, $email, $nome, $senha] = $argv + [null, null, null, null];
if ($email && $senha) {
    $st = $pdo->prepare('INSERT INTO usuarios (nome, email, senha_hash, papel) VALUES (?, ?, ?, "admin")
                         ON DUPLICATE KEY UPDATE nome = VALUES(nome), senha_hash = VALUES(senha_hash)');
    $st->execute([$nome ?: 'Admin', strtolower($email), password_hash($senha, PASSWORD_DEFAULT)]);
    echo "admin pronto: $email\n";
}
echo "tabelas ok\n";
