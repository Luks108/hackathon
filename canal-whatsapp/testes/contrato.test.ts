// Testes do que o gateway e o `acesso.ts` fazem SEM falar com o WhatsApp: números, acesso e a fila de saída.
// Rodam com `bun test` (dentro de canal-whatsapp/) e usam uma pasta de estado temporária: nunca tocam no estado real.
// Os números abaixo são fictícios (DDD 00).
import { afterAll, describe, expect, test } from 'bun:test'
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'

const ESTADO = mkdtempSync(join(tmpdir(), 'wa-teste-'))
process.env.WHATSAPP_STATE_DIR = ESTADO               // tem de vir antes de importar comum.ts (as constantes são lidas no import)
const comum = await import('../comum.ts')
const RAIZ = join(import.meta.dir, '..')

afterAll(() => rmSync(ESTADO, { recursive: true, force: true }))

function acesso(...args: string[]) {
  const r = Bun.spawnSync(['bun', 'acesso.ts', ...args], { cwd: RAIZ, env: { ...process.env, WHATSAPP_STATE_DIR: ESTADO } })
  return { codigo: r.exitCode, saida: r.stdout.toString() + r.stderr.toString() }
}

describe('números', () => {
  test('digitos tira o @, o :device e tudo que não é dígito', () => {
    expect(comum.digitos('5500999990001@s.whatsapp.net')).toBe('5500999990001')
    expect(comum.digitos('5500999990001:12@s.whatsapp.net')).toBe('5500999990001')
    expect(comum.digitos(undefined)).toBe('')
    expect(comum.digitos(null)).toBe('')
  })

  test('mesmoNumero ignora o nono dígito dos celulares brasileiros e nada além', () => {
    expect(comum.mesmoNumero('5500999990001', '550099990001')).toBe(true)   // com e sem o 9
    expect(comum.mesmoNumero('5500999990001', '5500999990001')).toBe(true)
    expect(comum.mesmoNumero('5500999990001', '5500999990002')).toBe(false)
    expect(comum.mesmoNumero('5500999990001', '5511999990001')).toBe(false)  // outro DDD
  })

  test('jidDeNumero monta o endereço do WhatsApp só com dígitos', () => {
    expect(comum.jidDeNumero('+55 (00) 99999-0001')).toBe('5500999990001@s.whatsapp.net')
  })
})

describe('acesso (quem pode falar com o bot)', () => {
  test('sem arquivo, ninguém é liberado', () => {
    expect(comum.lerAcesso()).toEqual({ allowFrom: [], allowGroups: [] })
  })

  test('add recusa número curto e o primeiro liberado vira o DONO', () => {
    const curto = acesso('add', '123')
    expect(curto.codigo).toBe(1)
    expect(curto.saida).toContain('número completo')
    const primeiro = acesso('add', '5500999990001')
    expect(primeiro.codigo).toBe(0)
    expect(primeiro.saida).toContain('(DONO)')
    const segundo = acesso('add', '5500999990002')
    expect(segundo.saida).not.toContain('(DONO)')
    expect(comum.lerAcesso().allowFrom).toEqual(['5500999990001', '5500999990002'])
  })

  test('add repetido não duplica e rm remove', () => {
    acesso('add', '5500999990002')
    expect(comum.lerAcesso().allowFrom.filter((n: string) => n === '5500999990002').length).toBe(1)
    acesso('rm', '5500999990002')
    expect(comum.lerAcesso().allowFrom).toEqual(['5500999990001'])
  })

  test('grupo só entra com JID de grupo', () => {
    expect(acesso('grupo-add', '5500999990001').codigo).toBe(1)
    expect(acesso('grupo-add', '120363000000000000@g.us').codigo).toBe(0)
    expect(comum.lerAcesso().allowGroups).toEqual(['120363000000000000@g.us'])
    acesso('grupo-rm', '120363000000000000@g.us')
    expect(comum.lerAcesso().allowGroups).toEqual([])
  })

  test('status diz que o gateway nunca rodou quando não há status.json', () => {
    expect(acesso('status').saida).toContain('gateway nunca rodou')
  })

  test('o arquivo de acesso fica com os números como o worker espera ler (lista de strings)', () => {
    const bruto = JSON.parse(readFileSync(comum.ACCESS_FILE, 'utf8'))
    expect(Array.isArray(bruto.allowFrom)).toBe(true)
    expect(typeof bruto.allowFrom[0]).toBe('string')
  })
})

describe('fila de saída (o contrato com o worker)', () => {
  test('acesso teste enfileira um pedido "enviar" para o JID do número', () => {
    const antes = new Set(readdirSync(comum.OUTBOX_DIR))
    acesso('teste', '5500999990001', 'olá do teste')
    const novo = readdirSync(comum.OUTBOX_DIR).filter((n: string) => !antes.has(n) && n.endsWith('.json'))
    expect(novo.length).toBe(1)
    const pedido = JSON.parse(readFileSync(join(comum.OUTBOX_DIR, novo[0]!), 'utf8'))
    expect(pedido.op).toBe('enviar')
    expect(pedido.chat_id).toBe('5500999990001@s.whatsapp.net')
    expect(pedido.texto).toBe('olá do teste')
    expect(typeof pedido.id).toBe('string')
  })

  test('o nome do arquivo começa pelo instante: a ordem de envio é a ordem de criação', () => {
    const a = comum.enfileirar({ op: 'enviar', chat_id: 'x@s.whatsapp.net', texto: '1' })
    const b = comum.enfileirar({ op: 'enviar', chat_id: 'x@s.whatsapp.net', texto: '2' })
    const nomes = readdirSync(comum.OUTBOX_DIR).filter((n: string) => [a, b].some(id => n.startsWith(id)))
    expect([...nomes].sort()).toEqual(nomes.sort())
    expect(existsSync(join(comum.OUTBOX_DIR, `${a}.json`))).toBe(true)
  })

  test('mensagens técnicas do WhatsApp não são tratadas como mensagem de pessoa', () => {
    for (const t of ['protocolMessage', 'senderKeyDistributionMessage', 'reactionMessage']) expect(comum.ehTipoTecnico(t)).toBe(true)
    for (const t of ['conversation', 'extendedTextMessage', 'imageMessage', 'audioMessage', 'stickerMessage', 'locationMessage', '']) expect(comum.ehTipoTecnico(t)).toBe(false)
  })

  test('escreverAtomico não deixa arquivo temporário para trás', () => {
    comum.escreverAtomico(join(ESTADO, 'x.json'), '{}')
    expect(readdirSync(ESTADO).some((n: string) => n.includes('.tmp-'))).toBe(false)
  })
})
