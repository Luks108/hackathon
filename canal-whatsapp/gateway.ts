#!/usr/bin/env bun
// GATEWAY — único dono da conexão Baileys. Roda como serviço (systemd --user), independente da
// sessão Claude: o WhatsApp fica online mesmo com o Claude fechado, e as mensagens esperam em
// inbound.jsonl.
//
// Pareamento: na primeira vez grava qr.png (e imprime no log). Alternativa sem câmera:
// WA_PAIR_PHONE=5587999999999 bun gateway.ts → imprime um código de 8 letras para digitar em
// WhatsApp → Aparelhos conectados → Conectar com número de telefone.

import makeWASocket, {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  getContentType,
  makeCacheableSignalKeyStore,
  normalizeMessageContent,
  useMultiFileAuthState,
  type WAMessage,
  type AnyMessageContent,
} from '@whiskeysockets/baileys'
import type { Boom } from '@hapi/boom'
import pino from 'pino'
import QR from 'qrcode'
import qrTerminal from 'qrcode-terminal'
import { existsSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'fs'
import { extname, join, basename } from 'path'
import {
  ACCESS_FILE, AUTH_DIR, DESCONHECIDOS_LOG, ENVIADAS_LOG, GATEWAY_PID, INBOUND_LOG, MIDIA_DIR, OUTBOX_DIR,
  QR_PNG, RESULTADOS_DIR, STATE_DIR, STATUS_FILE,
  anexarJsonl, digitos, escreverAtomico, garantirDiretorios, lerAcesso, lerPid, mesmoNumero, processoVivo,
  type Inbound, type Pedido, type Resultado,
} from './comum.ts'

const log = (m: string) => console.log(`[${new Date().toISOString()}] ${m}`)

// O libsignal despeja a sessão inteira (com chaves privadas) no console a cada renegociação: fora do journal.
const consoleOriginal = console.log.bind(console)
console.log = (...a: unknown[]) => {
  if (typeof a[0] === 'string' && /^(Closing|Opening|Removing|Migrating) (open )?session/.test(a[0])) return
  consoleOriginal(...a)
}
console.info = console.log
const baileysLogger = pino({ level: process.env.WA_LOG_LEVEL ?? 'warn' })

// Mídia acima disso não é baixada (o modelo recebe só o aviso).
const LIMITE_MIDIA_BYTES = 25 * 1024 * 1024

// ----- trava: um gateway por máquina -----
garantirDiretorios()
const pidAntigo = lerPid(GATEWAY_PID)
if (pidAntigo && pidAntigo !== process.pid && processoVivo(pidAntigo)) {
  log(`já existe gateway vivo (pid ${pidAntigo}) — saindo para não disputar o login`)
  process.exit(0)
}
writeFileSync(GATEWAY_PID, String(process.pid))

// ----- versão do WhatsApp Web -----
// O Baileys traz a versão fixa no código e o WhatsApp recusa builds velhas com 405 antes mesmo do QR
// (incidente do Alexandre, 28/07/2026). A fonte que acompanha as builds reais é wppconnect/wa-version.
const VERSAO_EMBUTIDA: [number, number, number] = [2, 3000, 1052612007]
const VERSAO_CACHE = join(STATE_DIR, 'wa-version.json')

async function escolherVersao(): Promise<[number, number, number]> {
  const parse = (s: unknown): [number, number, number] | null => {
    const m = typeof s === 'string' ? s.match(/^2\.3000\.(\d+)/) : null
    return m ? [2, 3000, Number(m[1])] : null
  }
  try {
    const r = await fetch('https://raw.githubusercontent.com/wppconnect-team/wa-version/main/versions.json', { signal: AbortSignal.timeout(5000) })
    const v = parse((await r.json()).currentVersion)
    if (v && v[2] >= VERSAO_EMBUTIDA[2]) {
      writeFileSync(VERSAO_CACHE, JSON.stringify(v))
      return v
    }
  } catch (e) { log(`wa-version: rede falhou (${e}) — tentando cache`) }
  try {
    const v = JSON.parse(readFileSync(VERSAO_CACHE, 'utf8'))
    if (Array.isArray(v) && v[2] >= VERSAO_EMBUTIDA[2]) return v as [number, number, number]
  } catch {}
  return VERSAO_EMBUTIDA
}

// ----- estado -----
let sock: ReturnType<typeof makeWASocket> | null = null
let conectado = false
let tentativas = 0
let encerrando = false
const cacheMsgs = new Map<string, WAMessage>() // para citar (reply_to) e reagir

function status(extra: Record<string, unknown> = {}) {
  escreverAtomico(STATUS_FILE, JSON.stringify({
    conectado, eu: digitos(sock?.user?.id), pid: process.pid, atualizado: new Date().toISOString(), ...extra,
  }))
}

function guardarNoCache(m: WAMessage) {
  if (!m.key.id) return
  cacheMsgs.set(m.key.id, m)
  if (cacheMsgs.size > 500) cacheMsgs.delete(cacheMsgs.keys().next().value!)
}

// ----- conexão -----
async function conectar() {
  if (sock) {
    try { sock.ev.removeAllListeners('connection.update') } catch {}
    try { sock.end(undefined) } catch {}
    sock = null
  }
  const versao = await escolherVersao()
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  log(`conectando com WhatsApp Web ${versao.join('.')}`)

  const s = makeWASocket({
    auth: { creds: state.creds, keys: makeCacheableSignalKeyStore(state.keys, baileysLogger) },
    logger: baileysLogger,
    version: versao,
    // Pareamento por código só é aceito com um navegador "conhecido"; nome inventado dá erro no celular.
    browser: Browsers.ubuntu('Chrome'),
    syncFullHistory: false,
    markOnlineOnConnect: false,
    getMessage: async key => (key.id ? cacheMsgs.get(key.id)?.message ?? undefined : undefined),
  })
  sock = s
  s.ev.on('creds.update', saveCreds)

  // Pareamento por código (sem QR): só quando ainda não há login. O pedido vai no primeiro evento de QR,
  // quando o socket já está pronto para isso (pedir antes faz o celular recusar o código).
  const telefone = process.env.WA_PAIR_PHONE?.replace(/\D/g, '')
  let codigoPedido = false
  async function pedirCodigo() {
    codigoPedido = true
    try {
      const codigo = await s.requestPairingCode(telefone!)
      log(`CÓDIGO DE PAREAMENTO: ${codigo}  (WhatsApp → Aparelhos conectados → Conectar com número de telefone)`)
      status({ codigoPareamento: codigo })
    } catch (e) { log(`pedido de código falhou: ${e}`) }
  }

  s.ev.on('connection.update', u => {
    if (u.qr && telefone && !state.creds.registered && !codigoPedido) void pedirCodigo()
    if (u.qr && !telefone) {
      QR.toFile(QR_PNG, u.qr).then(() => log(`QR gravado em ${QR_PNG} — escaneie no celular do bot`))
      qrTerminal.generate(u.qr, { small: true }, (out: string) => console.log(out))
    }
    if (u.connection === 'open') {
      conectado = true
      tentativas = 0
      rmSync(QR_PNG, { force: true })
      log(`conectado como ${digitos(s.user?.id)}`)
      status()
    }
    if (u.connection === 'close') {
      conectado = false
      const code = (u.lastDisconnect?.error as Boom | undefined)?.output?.statusCode
      status({ ultimoErro: code })
      if (code === DisconnectReason.loggedOut) {
        // Quarentena, nunca apagar: um 401 transitório não pode custar um pareamento novo.
        const destino = `${AUTH_DIR}.quarentena-${Date.now()}`
        try { renameSync(AUTH_DIR, destino); log(`desconectado (401) — auth movida para ${destino}; novo QR a seguir`) } catch {}
        garantirDiretorios()
      }
      if (encerrando) return
      tentativas++
      const espera = Math.min(60_000, 3000 * 2 ** Math.min(tentativas - 1, 5))
      log(`conexão caiu (código ${code}) — reconectando em ${espera / 1000}s`)
      setTimeout(() => void conectar(), espera)
    }
  })

  // O servidor confirmou o recebimento (ack) → não precisa reenviar.
  s.ev.on('messages.update', updates => {
    for (const { key, update } of updates) {
      if (key.fromMe && key.id && (update.status ?? 0) >= 2) semAck.delete(key.id)
    }
  })

  s.ev.on('messages.upsert', ({ messages, type }) => {
    if (type !== 'notify') return
    for (const m of messages) void receber(m).catch(e => log(`falha ao tratar mensagem: ${e}`))
  })
}

// ----- entrada -----
function textoDe(c: ReturnType<typeof normalizeMessageContent>): string {
  if (!c) return ''
  return c.conversation
    ?? c.extendedTextMessage?.text
    ?? c.imageMessage?.caption
    ?? c.videoMessage?.caption
    ?? c.documentMessage?.caption
    ?? c.documentWithCaptionMessage?.message?.documentMessage?.caption
    ?? ''
}

const TIPOS: Record<string, Inbound['tipo']> = {
  imageMessage: 'imagem', videoMessage: 'video', audioMessage: 'audio',
  documentMessage: 'documento', stickerMessage: 'figurinha',
}

async function receber(m: WAMessage) {
  if (m.key.fromMe || !m.message) return
  const chat = m.key.remoteJid ?? ''
  if (chat === 'status@broadcast') return
  guardarNoCache(m)

  const grupo = chat.endsWith('@g.us')
  // Baileys 7: o remetente pode chegar como @lid; o telefone vem no campo *Alt.
  const k = m.key as typeof m.key & { remoteJidAlt?: string; participantAlt?: string }
  const remetente = grupo
    ? digitos(k.participantAlt?.includes('@s.whatsapp.net') ? k.participantAlt : k.participant)
    : digitos(chat.endsWith('@s.whatsapp.net') ? chat : k.remoteJidAlt)

  const acesso = lerAcesso()
  const liberado = grupo ? acesso.allowGroups.includes(chat) : acesso.allowFrom.some(n => mesmoNumero(n, remetente))
  if (!liberado) {
    // Silêncio para quem não está na lista; o dono consulta com `bun acesso.ts desconhecidos`.
    anexarJsonl(DESCONHECIDOS_LOG, { ts: Date.now(), chat, remetente, nome: m.pushName ?? '' })
    log(`ignorado: ${grupo ? 'grupo ' + chat : remetente || chat} (fora do ${basename(ACCESS_FILE)})`)
    return
  }

  const conteudo = normalizeMessageContent(m.message)
  const tipoBruto = getContentType(conteudo) ?? ''
  const tipo = TIPOS[tipoBruto] ?? (textoDe(conteudo) ? 'texto' : 'outro')
  const reg: Inbound = {
    id: m.key.id ?? '', chat_id: chat, remetente, nome: m.pushName ?? remetente,
    ts: Number(m.messageTimestamp ?? Math.floor(Date.now() / 1000)),
    texto: textoDe(conteudo), tipo, grupo,
  }

  if (TIPOS[tipoBruto]) {
    const midia = (conteudo as any)[tipoBruto]
    const tamanho = Number(midia?.fileLength ?? 0)
    reg.mime = midia?.mimetype
    if (tamanho <= LIMITE_MIDIA_BYTES) {
      try {
        const buf = await downloadMediaMessage(m, 'buffer', {}, { logger: baileysLogger, reuploadRequest: sock!.updateMediaMessage })
        const ext = extensao(reg.mime, midia?.fileName)
        reg.arquivo = join(MIDIA_DIR, `${reg.ts}-${reg.id}${ext}`)
        writeFileSync(reg.arquivo, buf, { mode: 0o600 })
      } catch (e) { log(`download de mídia falhou (${reg.id}): ${e}`) }
    } else {
      reg.texto += `\n[mídia de ${Math.round(tamanho / 1048576)} MB não baixada — acima do limite]`
    }
  }

  anexarJsonl(INBOUND_LOG, reg)
  log(`recebida de ${reg.nome} (${tipo})`)
}

function extensao(mime?: string, nome?: string): string {
  if (nome && extname(nome)) return extname(nome)
  const mapa: Record<string, string> = {
    'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'video/mp4': '.mp4',
    'audio/ogg; codecs=opus': '.ogg', 'audio/ogg': '.ogg', 'audio/mp4': '.m4a', 'audio/mpeg': '.mp3', 'application/pdf': '.pdf',
  }
  return mapa[mime ?? ''] ?? ''
}

// ----- saída -----
function conteudoDeArquivo(path: string, legenda?: string): AnyMessageContent {
  const ext = extname(path).toLowerCase()
  if (['.jpg', '.jpeg', '.png', '.webp', '.gif'].includes(ext)) return { image: { url: path }, caption: legenda }
  if (['.mp4', '.mov', '.webm'].includes(ext)) return { video: { url: path }, caption: legenda }
  if (['.ogg', '.opus'].includes(ext)) return { audio: { url: path }, mimetype: 'audio/ogg; codecs=opus', ptt: true }
  if (['.mp3', '.m4a', '.wav'].includes(ext)) return { audio: { url: path }, mimetype: ext === '.mp3' ? 'audio/mpeg' : 'audio/mp4' }
  return { document: { url: path }, fileName: basename(path), mimetype: 'application/octet-stream', caption: legenda }
}

// Um número digitado (com ou sem o 9) vira o JID que o WhatsApp realmente usa para ele.
const jidsResolvidos = new Map<string, string>()
async function resolverJid(s: ReturnType<typeof makeWASocket>, jid: string): Promise<string> {
  if (!jid.endsWith('@s.whatsapp.net')) return jid
  if (!jidsResolvidos.has(jid)) {
    const [r] = (await s.onWhatsApp(jid).catch(() => undefined)) ?? []
    jidsResolvidos.set(jid, r?.exists ? r.jid : jid)
  }
  return jidsResolvidos.get(jid)!
}

// Mensagens enviadas ficam no cache: se o celular do destinatário não conseguir decifrar (comum logo após
// parear), ele pede reenvio e o Baileys busca o conteúdo em getMessage. Sem isso, o texto some.
// semAck: enviadas que o servidor ainda não confirmou. Se a conexão cai logo depois do envio (503 em 02/11
// engoliu a resposta do cupom), reenviamos uma vez ao reconectar.
const semAck = new Map<string, { chat: string; conteudo: AnyMessageContent; em: number; reenviada: boolean }>()

async function enviar(s: ReturnType<typeof makeWASocket>, chat: string, conteudo: AnyMessageContent, quoted?: WAMessage, reenviada = false) {
  const r = await s.sendMessage(chat, conteudo, { quoted })
  if (r?.key.id) {
    guardarNoCache(r)
    semAck.set(r.key.id, { chat, conteudo, em: Date.now(), reenviada })
  }
  return r
}

setInterval(() => {
  if (!conectado || !sock) return
  for (const [id, m] of semAck) {
    if (Date.now() - m.em < 15_000) continue
    semAck.delete(id)
    if (m.reenviada) { log(`sem confirmação do servidor mesmo após reenvio (${id})`); continue }
    log(`sem confirmação do servidor em 15s — reenviando (${id})`)
    void enviar(sock, m.chat, m.conteudo, undefined, true).catch(e => log(`reenvio falhou: ${e}`))
  }
}, 5000)

async function executar(p: Pedido): Promise<Resultado> {
  const s = sock!
  p = { ...p, chat_id: await resolverJid(s, p.chat_id) }
  if (p.op === 'digitando') {
    await s.sendPresenceUpdate(p.ligado ? 'composing' : 'paused', p.chat_id)
    return { id: p.id, ok: true }
  }
  if (p.op === 'reagir') {
    const alvo = cacheMsgs.get(p.message_id)
    const key = alvo?.key ?? { remoteJid: p.chat_id, id: p.message_id, fromMe: false }
    await s.sendMessage(p.chat_id, { react: { text: p.emoji, key } })
    return { id: p.id, ok: true }
  }
  const citada = p.responder_a ? cacheMsgs.get(p.responder_a) : undefined
  const ids: string[] = []
  const arquivos = p.arquivos ?? []
  // Com arquivos, o texto vira legenda do primeiro (quando o tipo aceita legenda).
  if (arquivos.length === 0 && p.texto) {
    const r = await enviar(s, p.chat_id, { text: p.texto }, citada)
    if (r?.key.id) ids.push(r.key.id)
  }
  for (const a of arquivos) if (!existsSync(a)) throw new Error(`arquivo não existe: ${a}`)
  for (const [i, a] of arquivos.entries()) {
    const r = await enviar(s, p.chat_id, conteudoDeArquivo(a, i === 0 ? p.texto : undefined), i === 0 ? citada : undefined)
    if (r?.key.id) ids.push(r.key.id)
  }
  await s.sendPresenceUpdate('paused', p.chat_id).catch(() => {})
  anexarJsonl(ENVIADAS_LOG, { ts: Date.now(), chat_id: p.chat_id, texto: p.texto, arquivos, ids })
  return { id: p.id, ok: true, ids }
}

let drenando = false
async function drenarOutbox() {
  if (drenando || !conectado || !sock) return
  drenando = true
  try {
    for (const nome of readdirSync(OUTBOX_DIR).filter(n => n.endsWith('.json')).sort()) {
      const path = join(OUTBOX_DIR, nome)
      let pedido: Pedido
      try { pedido = JSON.parse(readFileSync(path, 'utf8')) } catch { continue } // ainda sendo escrito
      let res: Resultado
      try { res = await executar(pedido) } catch (e) { res = { id: pedido.id, ok: false, erro: String(e) } }
      escreverAtomico(join(RESULTADOS_DIR, nome), JSON.stringify(res))
      rmSync(path, { force: true })
      if (!res.ok) log(`envio falhou (${pedido.id}): ${res.erro}`)
    }
    // Resultados velhos não interessam a ninguém depois de 10 min.
    const limite = Date.now() - 10 * 60_000
    for (const nome of readdirSync(RESULTADOS_DIR)) {
      if (parseInt(nome, 10) < limite) rmSync(join(RESULTADOS_DIR, nome), { force: true })
    }
  } finally { drenando = false }
}
setInterval(() => void drenarOutbox(), 400)

// ----- ciclo de vida -----
function sair() {
  encerrando = true
  conectado = false
  status({ parado: true })
  try { sock?.end(undefined) } catch {}
  if (lerPid(GATEWAY_PID) === process.pid) rmSync(GATEWAY_PID, { force: true })
  process.exit(0)
}
process.on('SIGINT', sair)
process.on('SIGTERM', sair)
process.on('unhandledRejection', e => log(`unhandledRejection: ${e}`))

if (lerAcesso().allowFrom.length === 0) log(`ATENÇÃO: ${ACCESS_FILE} sem números — ninguém será atendido. Use: bun acesso.ts add <numero>`)
void conectar()
