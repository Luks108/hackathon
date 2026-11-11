<?php
// Pacote de prova exportável: o dono de uma consulta baixa um ZIP que um terceiro reconfere sem acesso ao sistema.
//
//   GET /api/perguntas/{id}/prova[?formato=zip|json]     uma consulta
//   GET /api/provas[?ids=1,2,3][&formato=zip|json]       várias, na ORDEM PEDIDA, sem repetir (sem ids: as concluídas da conta, da mais antiga à
//                                                        mais nova, até 100)
//
// Tudo sai do que o site já guarda (perguntas + eventos). Nenhum campo é inventado: o que o worker não informou sai
// como null com o motivo. Só o dono lê; para qualquer outro a consulta "não existe" (404), como nos eventos.

declare(strict_types=1);
if (!defined('API')) { http_response_code(404); exit; }

const PROVA_FORMATO = 'fornexia-prova';
const PROVA_VERSAO_FORMATO = 1;
const PROVA_MAX_REGISTROS = 100;
// Teto do pacote inteiro (soma dos bytes de todos os arquivos, antes de zipar). Um dossiê normal de 100 consultas tem uns 0,5 MB.
// O ZIP é montado em memória, então sem teto uma conta com respostas enormes poderia estourar a memória do PHP e dar erro 500.
const PROVA_MAX_BYTES = 5 * 1024 * 1024;

/** Troca byte inválido por U+FFFD. Texto raspado de portal pode vir com byte torto, e um só derrubaria o pacote inteiro. */
function prova_utf8(string $s): string {
    return json_decode(json_encode($s, JSON_INVALID_UTF8_SUBSTITUTE | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), true);
}

function prova_grande_demais(int $bytes): never {
    erro(422, sprintf('Pacote grande demais: ficaria com %s MB e o limite é %s MB. Reduza o número de consultas e exporte de novo.',
        number_format($bytes / 1048576, 1, ',', ''), number_format(PROVA_MAX_BYTES / 1048576, 0)));
}

const PROVA_SEM_AVALIACAO_PESSOAL = 'Não avaliado: o pacote não analisa o conteúdo em busca de dado pessoal, então não afirma que ele não existe.';
const PROVA_SEM_EXTRATOR = 'A versão do extrator não é registrada junto da evidência na coleta atual, por isso não é possível informá-la.';

/** Só o nome do arquivo, nunca um caminho (nem do Windows, nem do servidor). */
function prova_nome_de_arquivo(mixed $v): ?string {
    if (!is_string($v) || $v === '') return null;
    $nome = basename(str_replace('\\', '/', $v));
    return $nome === '' || $nome === '.' || $nome === '..' ? null : mb_substr($nome, 0, 200);
}

function prova_texto(mixed $v, int $max = 200): ?string {
    return is_string($v) && $v !== '' ? mb_substr($v, 0, $max) : null;
}

/** Um trecho citado, só com os campos conhecidos. Devolve também o que falta para a cadeia até o arquivo bruto estar completa. */
function prova_trecho(array $d, string $nomeNoZip): array {
    $trecho = is_string($d['trecho'] ?? null) ? prova_utf8($d['trecho']) : '';   // antes do hash: o arquivo, o hash e o JSON usam o mesmo texto
    $hashBruto = is_string($d['documento_hash'] ?? null) && preg_match('/^[0-9a-f]{64}$/', $d['documento_hash']) ? $d['documento_hash'] : null;
    $url = is_string($d['url'] ?? null) && preg_match('#^https?://#i', $d['url']) ? mb_substr($d['url'], 0, 500) : null;
    $linha = isset($d['linha']) && is_numeric($d['linha']) ? (int)$d['linha'] : null;
    $t = [
        'evidencia_id' => prova_texto($d['evidencia'] ?? null),
        'trecho' => $trecho,
        'trecho_sha256' => hash('sha256', $trecho),
        'trecho_sha256_nota' => 'Calculado na exportação sobre os bytes UTF-8 do campo "trecho". Prova que o texto não foi alterado depois; a origem é provada pelo hash do arquivo bruto.',
        'trecho_arquivo' => $nomeNoZip,
        'trecho_mascarado' => (bool)($d['trecho_mascarado'] ?? false),
        'url' => $url,
        'capturado_em' => prova_texto($d['capturado_em'] ?? null, 40),
        'arquivo_bruto' => prova_nome_de_arquivo($d['arquivo'] ?? null),
        'tabela' => prova_texto($d['tabela'] ?? null, 60),
        'linha' => $linha,
        'documento_hash' => $hashBruto,
        'documento_hash_algoritmo' => $hashBruto === null ? null : 'sha256',
        // O worker grava o booleano JSON true. Aceita também o inteiro 1, mas nada além disso ("true", 2, [] não valem).
        'hash_conferido_na_consulta' => in_array($d['hash_confere'] ?? null, [true, 1], true),
    ];
    $falta = [];
    foreach (['trecho' => $trecho !== '', 'url' => $url !== null, 'capturado_em' => $t['capturado_em'] !== null,
              'arquivo_bruto' => $t['arquivo_bruto'] !== null, 'tabela' => $t['tabela'] !== null, 'linha' => $linha !== null,
              'documento_hash' => $hashBruto !== null] as $campo => $ok) {
        if (!$ok) $falta[] = $campo;
    }
    if ($t['hash_conferido_na_consulta'] !== true) $falta[] = 'hash_conferido_na_consulta (o arquivo guardado não bateu com o hash)';
    return [$t, $falta];
}

/** Monta o registro de uma consulta a partir das linhas do banco. $p = linha de perguntas + nome do plano. */
function prova_registro(array $p, array $eventos): array {
    $resposta = '';
    $fontes = [];
    $final = null;
    foreach ($eventos as $e) {
        $d = $e['dados'] === null ? [] : (json_decode((string)$e['dados'], true) ?: []);
        if ($e['tipo'] === 'texto' && is_string($d['delta'] ?? null)) $resposta .= $d['delta'];
        elseif ($e['tipo'] === 'fonte') $fontes[] = $d;
        elseif ($e['tipo'] === 'fim' || $e['tipo'] === 'erro') $final = ['tipo' => $e['tipo']] + $d;
    }

    $trechos = [];
    $problemas = [];
    foreach ($fontes as $i => $d) {
        [$t, $falta] = prova_trecho($d, sprintf('trechos/%d-%d.txt', $p['id'], $i + 1));
        $trechos[] = $t;
        if ($falta) $problemas[] = 'trecho ' . ($i + 1) . ': falta ' . implode(', ', $falta);
    }

    $resposta = prova_utf8($resposta);
    $semResposta = trim($resposta) === '';

    if ($p['status'] === 'erro') {
        $prova = 'sem_prova';
        $motivo = 'A consulta terminou em erro: não há resposta entregue nem trecho conferido.';
    } elseif ($semResposta) {
        // Trecho sem resposta não sustenta nada: não há afirmação entregue para provar.
        $prova = 'sem_prova';
        $motivo = 'A consulta terminou sem texto de resposta, então os trechos listados não sustentam nenhuma resposta entregue.';
    } elseif ($trechos === []) {
        $prova = 'sem_prova';
        $motivo = 'A resposta não citou nenhum trecho conferido da fonte. Nenhum trecho de outra consulta foi usado para preencher.';
    } elseif ($problemas) {
        $prova = 'prova_incompleta';
        $motivo = 'Há trecho sem a cadeia completa até o arquivo bruto: ' . implode('; ', $problemas) . '.';
    } else {
        $prova = 'com_prova';
        $motivo = null;
    }

    // Quem respondeu e o fallback: só o que o worker informou no fim/erro. Ausente continua ausente.
    $informou = $final !== null && array_key_exists('modelo', $final) && is_string($final['modelo'] ?? null);
    $modelo = $informou
        ? ['pedido' => prova_texto($final['modelo_pedido'] ?? null), 'respondeu' => prova_texto($final['modelo']), 'motivo_ausente' => null]
        : ['pedido' => null, 'respondeu' => null,
           'motivo_ausente' => 'O worker não informou o modelo desta consulta (consulta anterior a este recurso ou encerrada pelo site).'];
    $trocas = [];
    foreach ($informou && is_array($final['trocas'] ?? null) ? $final['trocas'] : [] as $x) {
        if (!is_array($x)) continue;
        $trocas[] = ['de' => prova_texto($x['de'] ?? null), 'para' => prova_texto($x['para'] ?? null),
                     'motivo' => prova_texto($x['motivo'] ?? null), 'tentativa' => is_numeric($x['tentativa'] ?? null) ? (int)$x['tentativa'] : null];
    }
    $fallback = $informou
        ? ['houve_troca' => $trocas !== [], 'trocas' => $trocas,
           'modelos_tentados' => is_array($final['tentados'] ?? null) ? array_values(array_filter(array_map(fn($m) => prova_texto($m), $final['tentados']))) : null]
        : ['houve_troca' => null, 'trocas' => [], 'modelos_tentados' => null, 'motivo_ausente' => $modelo['motivo_ausente']];

    return [
        'pergunta_id' => (int)$p['id'],
        'pergunta' => prova_utf8((string)$p['texto']),
        'perguntada_em' => $p['criada_em'],
        'concluida_em' => $p['concluida_em'],
        'fuso_dos_horarios' => 'não registrado pelo banco (horário do servidor do site)',
        'status' => $p['status'],
        'resposta' => $p['status'] === 'erro' || $semResposta ? null : $resposta,
        'modelo' => $modelo,
        'fallback' => $fallback,
        // Não há detector confiável de dado pessoal no projeto (só regex de CPF, que não pega nome de pessoa). Por isso não se afirma
        // nem "tem" nem "não tem": fica nulo, com a nota.
        'perfil' => ['plano' => $p['plano'], 'entes' => json_decode((string)$p['tenants'], true) ?: [], 'dados_pessoais' => null,
                     'dados_pessoais_nota' => PROVA_SEM_AVALIACAO_PESSOAL],
        'prova' => $prova,
        'motivo_prova' => $motivo,
        'trechos' => $trechos,
        'versao_extrator' => null,
        'versao_extrator_nota' => PROVA_SEM_EXTRATOR,
    ];
}

/** Lê as consultas do usuário NA ORDEM EM QUE FORAM PEDIDAS (ids repetidos já saíram) e monta os registros, com 2 consultas ao banco no total.
 *  Recusa o que não existe ou ainda não terminou: o primeiro id problemático, na ordem pedida, define o erro. */
function prova_registros(int $usuarioId, ?array $ids): array {
    $pdo = db();
    if ($ids === null) {
        $st = $pdo->prepare('SELECT id FROM perguntas WHERE usuario_id = ? AND status IN ("concluida","erro") ORDER BY id DESC LIMIT ' . PROVA_MAX_REGISTROS);
        $st->execute([$usuarioId]);
        $ids = array_reverse(array_map('intval', $st->fetchAll(PDO::FETCH_COLUMN)));   // sem ids pedidos: da mais antiga à mais nova
        if ($ids === []) erro(404, 'Você ainda não tem consultas concluídas para exportar.');
    }
    $marcas = implode(',', array_fill(0, count($ids), '?'));

    $st = $pdo->prepare("SELECT p.id, p.texto, p.status, p.tenants, p.criada_em, p.concluida_em, pl.nome AS plano
                         FROM perguntas p JOIN planos pl ON pl.id = p.plano_id WHERE p.usuario_id = ? AND p.id IN ($marcas)");
    $st->execute([$usuarioId, ...$ids]);
    $perguntas = [];
    foreach ($st->fetchAll() as $p) $perguntas[(int)$p['id']] = $p;
    foreach ($ids as $id) {
        if (!isset($perguntas[$id])) erro(404, "A consulta $id não existe.");
        if (!in_array($perguntas[$id]['status'], ['concluida', 'erro'], true)) erro(409, "A consulta $id ainda está em andamento. Exporte depois que terminar.");
    }

    $ev = $pdo->prepare("SELECT pergunta_id, tipo, dados FROM eventos WHERE pergunta_id IN ($marcas) ORDER BY pergunta_id, seq");
    $ev->execute($ids);
    $eventos = [];
    $bytes = 0;
    foreach ($ev->fetchAll() as $e) {
        $bytes += strlen((string)$e['dados']);
        $eventos[(int)$e['pergunta_id']][] = $e;
    }
    if ($bytes > PROVA_MAX_BYTES * 4) prova_grande_demais($bytes);   // corte cedo; a conferência exata é feita no pacote montado

    return array_map(fn($id) => prova_registro($perguntas[$id], $eventos[$id] ?? []), $ids);
}

// ---------- arquivos do pacote ----------

const PROVA_VERIFICADOR = <<<'PY'
"""Reconfere este pacote de prova. Só biblioteca padrão do Python 3. Não acessa a internet.

    python verificar_prova.py                  confere os trechos; confere também os arquivos brutos se houver uma pasta "bruto" aqui
    python verificar_prova.py --bruto PASTA    confere o hash dos arquivos brutos que estiverem em PASTA
    python verificar_prova.py --bruto          o mesmo, usando a pasta "bruto" ao lado deste arquivo
"""
import hashlib, json, sys
from pathlib import Path

aqui = Path(__file__).resolve().parent
args = sys.argv[1:]
pasta = None
if "--bruto" in args:
    i = args.index("--bruto")
    pasta = Path(args[i + 1]) if i + 1 < len(args) and not args[i + 1].startswith("--") else aqui / "bruto"
elif (aqui / "bruto").is_dir():
    pasta = aqui / "bruto"
pacote = json.loads((aqui / "prova.json").read_text(encoding="utf-8"))
falhas = 0
sem_bruto = 0
for r in pacote["registros"]:
    print(f"\nConsulta {r['pergunta_id']}: {r['pergunta']}")
    print(f"  situação da prova: {r['prova']}" + (f" ({r['motivo_prova']})" if r["motivo_prova"] else ""))
    for t in r["trechos"]:
        dados = (aqui / t["trecho_arquivo"]).read_bytes()
        calculado = hashlib.sha256(dados).hexdigest()
        ok = calculado == t["trecho_sha256"] and dados.decode("utf-8") == t["trecho"]
        falhas += not ok
        print(f"  trecho {t['evidencia_id']}: {'CONFERE' if ok else 'NÃO CONFERE'}  sha256 {calculado[:16]}...")
        if not t["arquivo_bruto"] or not t["documento_hash"]:
            sem_bruto += 1
            print("    arquivo bruto: o pacote não traz o nome ou o hash dele (não há o que conferir)")
        elif pasta is None or not (pasta / t["arquivo_bruto"]).is_file():
            sem_bruto += 1
            print(f"    arquivo bruto {t['arquivo_bruto']}: NÃO CONFERIDO (não está na pasta de brutos)")
        else:
            h = hashlib.sha256((pasta / t["arquivo_bruto"]).read_bytes()).hexdigest()
            ok = h == t["documento_hash"]
            falhas += not ok
            print(f"    arquivo bruto {t['arquivo_bruto']}: {'CONFERE' if ok else 'NÃO CONFERE'} com o hash declarado")
print()
if sem_bruto:
    print(f"ATENÇÃO: a origem de {sem_bruto} trecho(s) NÃO foi conferida, porque falta o arquivo bruto.")
    print("         Os trechos só provam que o texto não foi alterado. Ponha os arquivos brutos numa pasta e use --bruto PASTA.")
print("Resultado:", "tudo o que foi conferido confere" if not falhas else f"{falhas} verificação(ões) falharam")
sys.exit(1 if falhas else 0)
PY;

function prova_leia_me(): string {
    $t = <<<'TXT'
PACOTE DE PROVA - FornexIA

O que é
  Cada consulta feita ao assistente sai neste pacote com a pergunta, a resposta entregue, os trechos
  literais da fonte que a sustentam e as impressões digitais (hash SHA-256) que permitem conferir que
  nada foi alterado. Você não precisa de acesso ao sistema nem de nenhuma ferramenta nossa.

Arquivos
  prova.json            os dados (abre em qualquer editor de texto)
  trechos/              um arquivo .txt por trecho citado, com o texto exato
  verificar_prova.py    conferência automática (opcional, Python 3, sem internet)
  LEIA-ME.txt           este arquivo

Como conferir um trecho (sem nenhuma ferramenta nossa)
  1. Abra prova.json e procure "trecho_sha256" do trecho que quer conferir.
  2. Calcule o SHA-256 do arquivo da pasta trechos/ indicado em "trecho_arquivo":
       Windows (PowerShell):   Get-FileHash .\trechos\ARQUIVO.txt -Algorithm SHA256
       Windows (cmd):          certutil -hashfile trechos\ARQUIVO.txt SHA256
       Linux / macOS:          sha256sum trechos/ARQUIVO.txt
  3. O resultado precisa ser igual ao "trecho_sha256". Se uma letra for diferente, o texto foi alterado.

Como conferir a origem (o arquivo bruto do portal)
  O trecho foi tirado de uma linha ("linha") de uma tabela ("tabela") de um arquivo capturado do portal
  ("arquivo_bruto"). O campo "documento_hash" é o SHA-256 desse arquivo no momento da captura
  ("capturado_em"). O arquivo bruto NÃO vai neste pacote, porque pode conter dados pessoais que o perfil
  de quem consultou não pode ver. Peça-o a quem emitiu o pacote e calcule o SHA-256 dele com o mesmo
  comando acima: tem de ser igual ao "documento_hash". Com a pasta dos arquivos brutos:
       python verificar_prova.py --bruto PASTA
  A pasta é opcional. Sem ela, o verificar_prova.py confere só os trechos e avisa, ao final, que a origem
  NÃO foi conferida (usa a pasta "bruto" ao lado dele, se existir). Sem o arquivo bruto não há como saber
  se o trecho veio mesmo daquele arquivo: o trecho só prova que o texto não foi alterado.

O que este pacote prova e o que não prova
  - Prova que o trecho e o hash do arquivo bruto são os que o sistema registrou na consulta.
  - O "trecho_sha256" foi calculado por nós na exportação. Ele protege o texto contra alteração
    posterior; quem prova a origem é o "documento_hash", que vem da captura.
  - Não prova que o portal ainda publica o mesmo conteúdo, nem que a resposta esteja livre de erros.
  - O pacote traz só os trechos que o agente abriu e conferiu (no máximo 3 por resposta).
  - "prova": "com_prova" = há trecho e a cadeia até o arquivo bruto está completa; "prova_incompleta" =
    falta algum dado da cadeia (o motivo está em "motivo_prova"); "sem_prova" = a resposta não citou
    trecho. Resposta sem prova nunca é preenchida com trecho de outra consulta.
  - "versao_extrator": a coleta atual não registra a versão do extrator; o campo fica vazio e explicado.
  - Horários do banco ("perguntada_em", "concluida_em") não têm fuso registrado.
  - "dados_pessoais" fica vazio (null): o pacote não analisa o conteúdo em busca de dado pessoal e, por isso,
    não afirma que ele não existe.
  - Texto com byte inválido (comum em página raspada) tem o byte trocado por U+FFFD antes do hash, no
    arquivo do trecho e no JSON, para os dois baterem.
  - Resposta vazia nunca é "com_prova": sem texto entregue, não há o que provar.
  - O pacote tem teto de 5 MB; acima disso a exportação recusa com uma mensagem pedindo menos consultas.
TXT;
    return str_replace("\n", "\r\n", $t) . "\r\n";
}

/** ZIP mínimo, sem compressão e sem a extensão zip do PHP (a hospedagem e o PHP local nem sempre a têm). */
function prova_zip(array $arquivos): string {
    $agora = time();
    $d = getdate($agora);
    $data = (($d['year'] - 1980) << 9) | ($d['mon'] << 5) | $d['mday'];
    $hora = ($d['hours'] << 11) | ($d['minutes'] << 5) | intdiv($d['seconds'], 2);
    $corpo = '';
    $central = '';
    foreach ($arquivos as $nome => $conteudo) {
        $crc = crc32($conteudo);
        $tam = strlen($conteudo);
        $nome = (string)$nome;
        $deslocamento = strlen($corpo);
        $corpo .= pack('VvvvvvVVVvv', 0x04034b50, 20, 0x0800, 0, $hora, $data, $crc, $tam, $tam, strlen($nome), 0) . $nome . $conteudo;
        $central .= pack('VvvvvvvVVVvvvvvVV', 0x02014b50, 20, 20, 0x0800, 0, $hora, $data, $crc, $tam, $tam, strlen($nome), 0, 0, 0, 0, 0, $deslocamento) . $nome;
    }
    $n = count($arquivos);
    return $corpo . $central . pack('VvvvvVVv', 0x06054b50, 0, 0, $n, $n, strlen($central), strlen($corpo), 0);
}

function prova_pacote(array $registros, bool $dossie): array {
    $doc = [
        'formato' => PROVA_FORMATO,
        'versao_formato' => PROVA_VERSAO_FORMATO,
        'escopo' => $dossie ? 'dossie' : 'consulta',
        'exportado_em' => gmdate('Y-m-d\TH:i:s\Z'),
        'algoritmo_hash' => 'sha256',
        'como_reconferir' => 'Veja LEIA-ME.txt.',
        'registros' => $registros,
    ];
    $json = json_encode($doc, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT | JSON_INVALID_UTF8_SUBSTITUTE | JSON_THROW_ON_ERROR);
    $arquivos = ['prova.json' => $json, 'LEIA-ME.txt' => prova_leia_me(), 'verificar_prova.py' => PROVA_VERIFICADOR . "\n"];
    foreach ($registros as $r) {
        foreach ($r['trechos'] as $t) $arquivos[$t['trecho_arquivo']] = $t['trecho'];
    }
    return [$json, $arquivos];
}

function prova_enviar(array $registros, bool $dossie, string $nomeBase): never {
    [$json, $arquivos] = prova_pacote($registros, $dossie);
    $total = array_sum(array_map('strlen', $arquivos));
    if ($total > PROVA_MAX_BYTES) prova_grande_demais($total);
    $formato = ($_GET['formato'] ?? 'zip') === 'json' ? 'json' : 'zip';
    header('Cache-Control: private, no-store');
    header('Content-Disposition: attachment; filename="' . $nomeBase . '.' . $formato . '"');
    if ($formato === 'json') {
        header('Content-Type: application/json; charset=utf-8');
        echo $json;
    } else {
        header('Content-Type: application/zip');
        echo prova_zip($arquivos);
    }
    exit;
}

// ---------- rotas ----------

function rota_prova(int $id): never {
    $u = exigir_login();
    prova_enviar(prova_registros((int)$u['id'], [$id]), false, "prova-fornexia-consulta-$id");
}

function rota_provas(): never {
    $u = exigir_login();
    $ids = null;
    if (isset($_GET['ids'])) {
        $partes = is_string($_GET['ids']) ? explode(',', $_GET['ids']) : [];
        foreach ($partes as $x) {
            if (!preg_match('/^\d{1,9}$/', $x) || (int)$x < 1) erro(400, 'O parâmetro "ids" precisa ser uma lista de números separados por vírgula.');
        }
        $ids = array_values(array_unique(array_map('intval', $partes)));
        if ($ids === [] || count($ids) > PROVA_MAX_REGISTROS) erro(400, 'Informe de 1 a ' . PROVA_MAX_REGISTROS . ' consultas.');
    }
    $registros = prova_registros((int)$u['id'], $ids);
    prova_enviar($registros, true, 'dossie-fornexia-' . count($registros) . '-consultas');
}
