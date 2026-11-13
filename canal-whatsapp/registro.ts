// Log estruturado do gateway: o MESMO formato do consulta/registro.py (NDJSON, um arquivo por subsistema em logs/).
//
//   registrar('gateway', 'envio', { op: 'enviar', ok: true, duracao_ms: 412 }, 'info', 'wa:3EB0...')
//
// Linha: ts (local, com milissegundos e fuso), nivel, subsistema, evento, request_id (quando há) e os campos do evento.
// Garantias, mesmo que quem chama erre: nunca derruba o gateway; nunca grava chave, token, telefone, CPF, e-mail nem o texto
// de uma mensagem (campos com esses nomes viram "[omitido]" e textos soltos passam por uma máscara); nível por LOG_NIVEL
// (debug, info, aviso, erro; padrão info); rotação por tamanho (LOG_MAX_MB, padrão 10; LOG_ARQUIVOS, padrão 5).
// Pasta: FORNEXIA_LOGS_DIR, senão logs/ na raiz do projeto (em `bun test`, uma pasta temporária).

import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'

export type Subsistema = 'gateway' | 'worker' | 'agente' | 'ferramentas' | 'seguranca' | 'saude'
export type Nivel = 'debug' | 'info' | 'aviso' | 'erro'

const NIVEIS: Record<Nivel, number> = { debug: 10, info: 20, aviso: 30, erro: 40 }
const SUBSISTEMAS = new Set<string>(['gateway', 'worker', 'agente', 'ferramentas', 'seguranca', 'saude'])
// Trechos que, em QUALQUER parte do nome de um campo, impedem o valor de entrar no log (pega o plural e as variações). Desenho seguro:
// o que não se conhece é omitido. A única exceção são as contagens ("tokens_entrada", "tamanho_texto"). Mesma regra do consulta/registro.py.
const PROIBIDOS_NO_NOME = ['chave', 'token', 'senha', 'password', 'secret', 'api_key', 'apikey', 'authorization', 'cookie', 'telefone', 'remetente',
  'chat_id', 'jid', 'texto', 'mensage', 'pergunta', 'conteudo', 'resposta', 'numero_wa']      // 'mensage' pega mensagem e mensagens
const PREFIXOS_DE_MEDIDA = ['tamanho_', 'qtd_']
const SUFIXOS_DE_MEDIDA = ['_len', '_tamanho', '_bytes', '_ms', '_s']
// Exceção por nome exato (um prefixo "tokens_" geral deixaria passar "tokens_acesso"): o trecho de alerta e as contagens de tokens de modelo.
const PERMITIDOS = ['trecho', 'tokens_entrada', 'tokens_saida', 'tokens_total']
const LIMITE_TEXTO = 300

const CPF = /(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)/g
const EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g
const TELEFONE = /(?<![\d.])(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}(?![\d.])/g
const SEGREDO = /\b(?:sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]{12,}|AIza[0-9A-Za-z_-]{20,}|eyJ[0-9A-Za-z_-]{20,})/gi

export function pasta(): string {
  const env = process.env.FORNEXIA_LOGS_DIR?.trim()
  if (env) return env
  if (process.env.NODE_ENV === 'test') return join(tmpdir(), 'fornexia-logs-teste')
  return join(import.meta.dir, '..', 'logs')
}

function nivelMinimo(): number {
  return NIVEIS[(process.env.LOG_NIVEL ?? 'info').trim().toLowerCase() as Nivel] ?? NIVEIS.info
}

function inteiro(nome: string, padrao: number): number {
  const n = parseInt(process.env[nome] ?? '', 10)
  return Number.isFinite(n) && n > 0 ? n : padrao
}

export function mascarar(texto: string): string {
  return texto.replace(SEGREDO, '[SEGREDO]').replace(EMAIL, '[EMAIL]').replace(CPF, '[CPF]').replace(TELEFONE, '[TEL]')
}

export function proibido(chave: string): boolean {
  const nome = chave.toLowerCase()
  if (PERMITIDOS.includes(nome) || PREFIXOS_DE_MEDIDA.some(p => nome.startsWith(p)) || SUFIXOS_DE_MEDIDA.some(p => nome.endsWith(p))) return false
  return PROIBIDOS_NO_NOME.some(p => nome.includes(p))
}

export function limpar(valor: unknown, chave = ''): unknown {
  if (proibido(chave)) return '[omitido]'
  if (typeof valor === 'string') return mascarar(valor).slice(0, LIMITE_TEXTO)
  if (Array.isArray(valor)) return valor.slice(0, 50).map(v => limpar(v, chave))
  if (valor && typeof valor === 'object') {
    return Object.fromEntries(Object.entries(valor as Record<string, unknown>).map(([k, v]) => [k, limpar(v, k)]))
  }
  if (valor === null || typeof valor === 'number' || typeof valor === 'boolean') return valor
  return limpar(String(valor), chave)
}

/** Horário local com milissegundos e fuso, igual ao do Python: 2026-11-12T20:11:03.412-03:00 */
export function agoraLocal(d = new Date()): string {
  const p = (n: number, w = 2) => String(n).padStart(w, '0')
  const desloc = -d.getTimezoneOffset()
  const a = Math.abs(desloc)
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}` +
    `${desloc >= 0 ? '+' : '-'}${p(Math.floor(a / 60))}:${p(a % 60)}`
}

function rotacionar(caminho: string, maximo: number, copias: number) {
  try {
    if (statSync(caminho).size < maximo) return
  } catch { return }
  try {
    for (let i = copias - 1; i >= 1; i--) {
      if (existsSync(`${caminho}.${i}`)) renameSync(`${caminho}.${i}`, `${caminho}.${i + 1}`)
    }
    renameSync(caminho, `${caminho}.1`)
  } catch { /* outro processo pode estar com o arquivo aberto (Windows): tenta de novo na próxima gravação */ }
}

/** Grava uma linha. Nunca levanta. */
export function registrar(subsistema: Subsistema, evento: string, campos: Record<string, unknown> = {}, nivel: Nivel = 'info', requestId?: string): void {
  try {
    if (!SUBSISTEMAS.has(subsistema) || NIVEIS[nivel] < nivelMinimo()) return
    const linha: Record<string, unknown> = { ts: agoraLocal(), nivel, subsistema, evento }
    if (requestId) linha.request_id = String(requestId).slice(0, 80)
    for (const [k, v] of Object.entries(campos)) linha[k] = limpar(v, k)
    const destino = pasta()
    mkdirSync(destino, { recursive: true })
    const caminho = join(destino, `${subsistema}.jsonl`)
    rotacionar(caminho, inteiro('LOG_MAX_MB', 10) * 1024 * 1024, inteiro('LOG_ARQUIVOS', 5))
    appendFileSync(caminho, JSON.stringify(linha) + '\n', 'utf8')
  } catch { /* o log jamais derruba o gateway */ }
}
