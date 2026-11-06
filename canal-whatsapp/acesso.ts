#!/usr/bin/env bun
// Quem pode falar com o bot. Só o dono roda isto, no terminal.
//
//   bun acesso.ts list
//   bun acesso.ts add 5587999999999        (o primeiro número adicionado é o DONO)
//   bun acesso.ts rm 5587999999999
//   bun acesso.ts grupo-add 1203...@g.us
//   bun acesso.ts grupo-rm 1203...@g.us
//   bun acesso.ts desconhecidos            (quem tentou falar e foi ignorado)
//   bun acesso.ts status
//   bun acesso.ts teste 5587999999999 "mensagem"   (envia pelo gateway)

import { existsSync, readFileSync } from 'fs'
import { DESCONHECIDOS_LOG, STATUS_FILE, enfileirar, garantirDiretorios, gravarAcesso, jidDeNumero, lerAcesso } from './comum.ts'

garantirDiretorios()
const [cmd, arg, ...resto] = process.argv.slice(2)
const a = lerAcesso()
const num = (s?: string) => (s ?? '').replace(/\D/g, '')

switch (cmd) {
  case 'add': {
    const n = num(arg)
    if (n.length < 12) { console.error('use o número completo com DDI e DDD, ex.: 5587999999999'); process.exit(1) }
    if (!a.allowFrom.includes(n)) a.allowFrom.push(n)
    gravarAcesso(a)
    console.log(`liberado: ${n}${a.allowFrom[0] === n ? ' (DONO)' : ''}`)
    break
  }
  case 'rm':
    a.allowFrom = a.allowFrom.filter(x => x !== num(arg))
    gravarAcesso(a)
    console.log('removido')
    break
  case 'grupo-add':
    if (!arg?.endsWith('@g.us')) { console.error('passe o JID do grupo (…@g.us) — veja em `desconhecidos`'); process.exit(1) }
    if (!a.allowGroups.includes(arg)) a.allowGroups.push(arg)
    gravarAcesso(a)
    console.log('grupo liberado')
    break
  case 'grupo-rm':
    a.allowGroups = a.allowGroups.filter(x => x !== arg)
    gravarAcesso(a)
    console.log('grupo removido')
    break
  case 'desconhecidos':
    if (existsSync(DESCONHECIDOS_LOG)) console.log(readFileSync(DESCONHECIDOS_LOG, 'utf8').trim().split('\n').slice(-20).join('\n'))
    else console.log('ninguém')
    break
  case 'status':
    console.log(existsSync(STATUS_FILE) ? readFileSync(STATUS_FILE, 'utf8') : 'gateway nunca rodou')
    break
  case 'teste': {
    const id = enfileirar({ op: 'enviar', chat_id: jidDeNumero(num(arg)), texto: resto.join(' ') || 'teste do canal ✅' })
    console.log(`enfileirado ${id}`)
    break
  }
  default:
    console.log(JSON.stringify(a, null, 2))
    console.log('\ncomandos: list | add <num> | rm <num> | grupo-add <jid> | grupo-rm <jid> | desconhecidos | status | teste <num> [texto]')
}
