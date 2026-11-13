// Peças compartilhadas entre o gateway (dono da conexão) e o canal (relay MCP).
//
// Arquitetura herdada da lição do plugin do Alexandre: UM processo segura o socket do WhatsApp.
// Vários donos do mesmo login se derrubam em loop de reconexão. Por isso:
//   gateway.ts  → único dono do Baileys; grava inbound.jsonl, consome outbox/
//   canal.ts    → sobe com a sessão Claude; lê inbound.jsonl, escreve outbox/
// Qualquer outro processo (backend, YOLO) também pode mandar WhatsApp escrevendo em outbox/.

import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'fs'
import { homedir } from 'os'
import { join } from 'path'

export const STATE_DIR = process.env.WHATSAPP_STATE_DIR ?? join(homedir(), '.claude', 'channels', 'whatsapp-hackathon')
export const AUTH_DIR = join(STATE_DIR, 'auth')
export const MIDIA_DIR = join(STATE_DIR, 'midia')
export const OUTBOX_DIR = join(STATE_DIR, 'outbox')
export const RESULTADOS_DIR = join(STATE_DIR, 'resultados')
export const INBOUND_LOG = join(STATE_DIR, 'inbound.jsonl')
export const ENVIADAS_LOG = join(STATE_DIR, 'enviadas.jsonl')
export const DESCONHECIDOS_LOG = join(STATE_DIR, 'desconhecidos.jsonl')
export const ACCESS_FILE = join(STATE_DIR, 'access.json')
export const STATUS_FILE = join(STATE_DIR, 'status.json')
export const QR_PNG = join(STATE_DIR, 'qr.png')
export const GATEWAY_PID = join(STATE_DIR, 'gateway.pid')
export const CANAL_LOCK = join(STATE_DIR, 'canal.lock')

export function garantirDiretorios(): void {
  for (const d of [STATE_DIR, AUTH_DIR, MIDIA_DIR, OUTBOX_DIR, RESULTADOS_DIR]) mkdirSync(d, { recursive: true, mode: 0o700 })
}

// ----- acesso -----
// allowFrom: números (só dígitos, com DDI). O primeiro é o DONO: recebe os pedidos de permissão.
// allowGroups: JIDs de grupo (…@g.us) liberados. Vazio = grupos ignorados.
export interface Acesso { allowFrom: string[]; allowGroups: string[] }

export function lerAcesso(): Acesso {
  try {
    const a = JSON.parse(readFileSync(ACCESS_FILE, 'utf8'))
    return { allowFrom: a.allowFrom ?? [], allowGroups: a.allowGroups ?? [] }
  } catch {
    return { allowFrom: [], allowGroups: [] }
  }
}

export function gravarAcesso(a: Acesso): void {
  escreverAtomico(ACCESS_FILE, JSON.stringify(a, null, 2) + '\n')
}

/** Só os dígitos da parte antes do @ e do : (device). `5587999999999:12@s.whatsapp.net` → `5587999999999`. */
// Tipos técnicos do WhatsApp: não são mensagens de pessoa (sincronização, apagar/editar, chaves, reações). Não viram "inbound".
// Foi um protocolMessage, logo após cada resposta do bot, que fazia o worker mandar "Por aqui eu respondo…" sem ninguém ter escrito.
const TIPOS_TECNICOS = new Set(['protocolMessage', 'senderKeyDistributionMessage', 'reactionMessage'])
export function ehTipoTecnico(tipoBruto: string): boolean { return TIPOS_TECNICOS.has(tipoBruto) }

/** O texto de quem escreve não pode abrir nem fechar a tag do canal (`<channel ...>`): o `<` ou `</` antes de "channel" vira um caractere neutro.
 *  Mora aqui, e não no canal.ts, para ser testável (o canal.ts sobe um servidor ao ser importado). Ataque AP-16 do catálogo. */
export function neutralizarTagDoCanal(texto: string): string { return texto.replace(/<\/?channel/gi, '‹channel') }

export function digitos(jid: string | null | undefined): string {
  if (!jid) return ''
  return jid.split('@')[0]!.split(':')[0]!.replace(/\D/g, '')
}

// Celulares brasileiros antigos existem no WhatsApp sem o 9 (ex.: 558799998888): compara ignorando esse 9.
export function mesmoNumero(a: string, b: string): boolean {
  const n = (x: string) => { const d = x.replace(/\D/g, ''); return /^55\d{2}9\d{8}$/.test(d) ? d.slice(0, 4) + d.slice(5) : d }
  return n(a) === n(b)
}

export function jidDeNumero(numero: string): string {
  return `${numero.replace(/\D/g, '')}@s.whatsapp.net`
}

// ----- arquivos -----
export function escreverAtomico(path: string, conteudo: string): void {
  const tmp = `${path}.tmp-${process.pid}`
  writeFileSync(tmp, conteudo, { mode: 0o600 })
  renameSync(tmp, path)
}

export function anexarJsonl(path: string, obj: unknown): void {
  appendFileSync(path, JSON.stringify(obj) + '\n', { mode: 0o600 })
}

export function processoVivo(pid: number): boolean {
  if (!pid || pid <= 1) return false
  try { process.kill(pid, 0); return true } catch { return false }
}

export function lerPid(path: string): number {
  try { return parseInt(readFileSync(path, 'utf8'), 10) || 0 } catch { return 0 }
}

// ----- contratos dos arquivos -----
export interface Inbound {
  id: string
  chat_id: string
  remetente: string        // dígitos do telefone, quando conhecido
  nome: string
  ts: number
  texto: string
  tipo: 'texto' | 'imagem' | 'video' | 'audio' | 'documento' | 'figurinha' | 'outro'
  arquivo?: string         // caminho absoluto da mídia já baixada
  mime?: string
  grupo: boolean
}

export type Pedido =
  | { id: string; op: 'enviar'; chat_id: string; texto?: string; arquivos?: string[]; responder_a?: string; request_id?: string }
  | { id: string; op: 'reagir'; chat_id: string; message_id: string; emoji: string; request_id?: string }
  | { id: string; op: 'digitando'; chat_id: string; ligado: boolean; request_id?: string }

export interface Resultado { id: string; ok: boolean; ids?: string[]; erro?: string }

/** Enfileira um pedido para o gateway. O nome começa pelo instante para manter a ordem de envio. */
type SemId<T> = T extends unknown ? Omit<T, 'id'> & { id?: string } : never
export function enfileirar(p: SemId<Pedido>): string {
  const id = p.id ?? `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  escreverAtomico(join(OUTBOX_DIR, `${id}.json`), JSON.stringify({ ...p, id }))
  return id
}

export function existe(path: string): boolean { return existsSync(path) }
