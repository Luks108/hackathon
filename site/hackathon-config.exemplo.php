<?php
// Copie para site/hackathon-config.php (ignorado pelo git) e ajuste. Em produção, o deploy.sh gera este arquivo
// FORA do public_html, a partir do .env. Nada aqui pode ir para o repositório.

const AMBIENTE = 'dev';              // 'dev' desliga o cookie Secure (http://localhost). Em produção: 'prod'
const DB_HOST = '127.0.0.1';
const DB_PORT = 3307;                // contêiner de site/dev/docker-compose.yml
const DB_NAME = 'hackathon';
const DB_USER = 'hackathon';
const DB_PASS = 'dev-senha';
const WORKER_KEY = 'troque-por-uma-chave-longa-e-aleatoria';   // mínimo 24 caracteres
const API_KEY = '';                  // legado do modelo antigo; não é mais usado
const INFERENCIA_URL = '';           // legado do modelo antigo; não é mais usado
