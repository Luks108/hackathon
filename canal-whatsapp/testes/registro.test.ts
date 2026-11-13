// Testes do log estruturado do gateway (registro.ts): formato, privacidade, níveis, rotação e o contrato com o registro.py.
// Rodam com `bun test` (dentro de canal-whatsapp/) e usam uma pasta temporária: nunca tocam nos logs de verdade.
import { afterAll, beforeEach, describe, expect, test } from 'bun:test'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'

const PASTA = mkdtempSync(join(tmpdir(), 'wa-log-'))
process.env.FORNEXIA_LOGS_DIR = PASTA
const R = await import('../registro.ts')
const RAIZ = join(import.meta.dir, '..', '..')

afterAll(() => rmSync(PASTA, { recursive: true, force: true }))
beforeEach(() => {
  delete process.env.LOG_NIVEL
  delete process.env.LOG_MAX_MB
  for (const s of ['gateway', 'saude', 'seguranca']) for (const sufixo of ['', '.1', '.2']) rmSync(join(PASTA, `${s}.jsonl${sufixo}`), { force: true })
})

const ler = (sub = 'gateway') => {
  const arq = join(PASTA, `${sub}.jsonl`)
  return existsSync(arq) ? readFileSync(arq, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l)) : []
}

describe('formato', () => {
  test('cada linha tem ts local com milissegundos e fuso, nível, subsistema, evento e request_id', () => {
    R.registrar('gateway', 'envio', { op: 'enviar', ok: true, duracao_ms: 412 }, 'info', 'wa:ABC')
    const [l] = ler()
    expect(l.ts).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$/)
    expect([l.nivel, l.subsistema, l.evento, l.request_id, l.op, l.ok, l.duracao_ms]).toEqual(['info', 'gateway', 'envio', 'wa:ABC', 'enviar', true, 412])
  })

  test('sem request_id o campo some; subsistema desconhecido não grava', () => {
    R.registrar('saude', 'componente_iniciou', { componente: 'gateway' })
    expect('request_id' in ler('saude')[0]).toBe(false)
    R.registrar('banana' as never, 'x')
    expect(existsSync(join(PASTA, 'banana.jsonl'))).toBe(false)
  })

  test('nível padrão info; LOG_NIVEL muda; valor inválido volta para info', () => {
    R.registrar('gateway', 'a', {}, 'debug')
    R.registrar('gateway', 'b', {}, 'info')
    process.env.LOG_NIVEL = 'debug'
    R.registrar('gateway', 'c', {}, 'debug')
    process.env.LOG_NIVEL = 'erro'
    R.registrar('gateway', 'd', {}, 'aviso')
    R.registrar('gateway', 'e', {}, 'erro')
    process.env.LOG_NIVEL = 'banana'
    R.registrar('gateway', 'f', {}, 'debug')
    expect(ler().map(l => l.evento)).toEqual(['b', 'c', 'e'])
  })

  test('nunca levanta, nem com valor estranho', () => {
    expect(() => R.registrar('gateway', 'x', { circular: (() => { const o: any = {}; o.o = o; return o })(), f: () => 1 })).not.toThrow()
  })
})

describe('privacidade', () => {
  test('campos sensíveis viram [omitido]; contagens com palavra proibida no nome passam (regressão do tokens_entrada)', () => {
    R.registrar('gateway', 'x', { token: 't', telefone: '5587999990001', texto: 'conteudo', chat_id: 'c', remetente: 'r', api_key: 'k', access_token: 'a',
      tokens_entrada: 100, tamanho_texto: 42, texto_len: 7, usuario: 3 })
    const [l] = ler()
    for (const k of ['token', 'telefone', 'texto', 'chat_id', 'remetente', 'api_key', 'access_token']) expect(l[k]).toBe('[omitido]')
    expect([l.tokens_entrada, l.tamanho_texto, l.texto_len, l.usuario]).toEqual([100, 42, 7, 3])
  })

  test('plural e variações de nome sensível também são omitidos (desenho seguro: por trecho do nome)', () => {
    R.registrar('gateway', 'x', { telefones: ['5587999990001'], mensagens: ['oi'], perguntas: ['a'], senhas: ['s'], chaves: ['k'], textos: ['t'], tokens_acesso: 'a' })
    const [l] = ler()
    for (const k of ['telefones', 'mensagens', 'perguntas', 'senhas', 'chaves', 'textos', 'tokens_acesso']) expect(l[k]).toBe('[omitido]')
    expect(readFileSync(join(PASTA, 'gateway.jsonl'), 'utf8')).not.toContain('999990001')
  })

  test('textos soltos passam por máscara e o que sobra não contém o dado', () => {
    R.registrar('gateway', 'x', { erro: 'CPF 123.456.789-09, tel +55 (87) 99999-0001, joao@exemplo.com, chave sk-abcdefghijklmnop1234' })
    const bruto = readFileSync(join(PASTA, 'gateway.jsonl'), 'utf8')
    for (const s of ['123.456.789-09', '99999-0001', 'joao@exemplo.com', 'sk-abcdefghijklmnop1234']) expect(bruto).not.toContain(s)
    for (const m of ['[CPF]', '[TEL]', '[EMAIL]', '[SEGREDO]']) expect(ler()[0].erro).toContain(m)
  })

  test('um erro com o jid do contato não vaza o número', () => {
    R.registrar('gateway', 'envio', { ok: false, erro: 'Error: not-authorized 5587999990001@s.whatsapp.net' }, 'erro')
    expect(readFileSync(join(PASTA, 'gateway.jsonl'), 'utf8')).not.toContain('999990001')
  })

  test('CNPJ e número de contrato não viram telefone; texto longo é cortado', () => {
    R.registrar('gateway', 'x', { cnpj: '12345678000190', n: '1/2026', longo: 'a'.repeat(1000) })
    const [l] = ler()
    expect([l.cnpj, l.n, l.longo.length]).toEqual(['12345678000190', '1/2026', 300])
  })
})

describe('rotação', () => {
  test('arquivo acima de LOG_MAX_MB gira para .1 e o novo evento abre um arquivo novo', () => {
    process.env.LOG_MAX_MB = '1'
    writeFileSync(join(PASTA, 'gateway.jsonl'), 'x'.repeat(1024 * 1024 + 10))
    R.registrar('gateway', 'novo')
    expect(existsSync(join(PASTA, 'gateway.jsonl.1'))).toBe(true)
    expect(ler().map(l => l.evento)).toEqual(['novo'])
  })
})

describe('contrato com o registro.py', () => {
  test('mesmo evento nos dois lados: mesmos campos, mesma máscara, mesmos omitidos', () => {
    const dados = { op: 'enviar', tokens_entrada: 7, tamanho_texto: 3, telefone: '5587999990001', erro: 'cpf 123.456.789-09 joao@x.com', trecho: 'oi 123.456.789-09' }
    R.registrar('gateway', 'contrato', dados, 'aviso', 'wa:X')
    const ts = ler()[0]
    const py = [process.env.PYTHON ?? '', join(RAIZ, '.venv', 'Scripts', 'python.exe'), join(RAIZ, '.venv', 'bin', 'python'), 'python3', 'python']
      .filter(Boolean).find(p => { try { return Bun.spawnSync([p, '--version']).exitCode === 0 } catch { return false } })
    if (!py) return       // sem Python na máquina: o teste do lado Python (chat/testes/test_registro.py) cobre o outro lado
    const codigo = 'import sys,json;sys.path.insert(0,sys.argv[1]);import registro;registro.registrar("gateway","contrato","aviso",request_id="wa:X",**json.loads(sys.argv[2]))'
    const pasta2 = mkdtempSync(join(tmpdir(), 'wa-log-py-'))
    const r = Bun.spawnSync([py, '-c', codigo, join(RAIZ, 'consulta'), JSON.stringify(dados)], { env: { ...process.env, FORNEXIA_LOGS_DIR: pasta2 } })
    expect(r.exitCode).toBe(0)
    const python = JSON.parse(readFileSync(join(pasta2, 'gateway.jsonl'), 'utf8').trim())
    rmSync(pasta2, { recursive: true, force: true })
    const sem = (o: Record<string, unknown>) => { const { ts, ...resto } = o; return resto }
    expect(sem(ts)).toEqual(sem(python))
    expect(Object.keys(ts)).toEqual(Object.keys(python))       // até a ordem das chaves
  })
})
