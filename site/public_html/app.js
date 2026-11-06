// Front mínimo: login → registrar com foto (câmera do celular) → lista com a análise da IA.
const $ = s => document.querySelector(s)

async function api(caminho, opcoes = {}) {
  const r = await fetch(`api/${caminho}`, { credentials: 'same-origin', ...opcoes })
  const dados = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(dados.erro || `erro ${r.status}`)
  return dados
}

function mostrar(logado) {
  $('#tela-login').hidden = logado
  $('#tela-app').hidden = !logado
  $('#sair').hidden = !logado
  if (logado) carregar()
}

async function carregar() {
  const lista = await api('registros')
  $('#lista').replaceChildren(...lista.map(r => {
    const el = document.createElement('div')
    el.className = 'cartao reg'
    if (r.foto) {
      const img = document.createElement('img')
      img.src = r.foto
      img.alt = r.titulo
      el.append(img)
    }
    const txt = document.createElement('div')
    const t = document.createElement('strong')
    t.textContent = r.titulo
    const meta = document.createElement('small')
    meta.textContent = ` · ${r.autor ?? r.origem} · ${new Date(r.criado_em.replace(' ', 'T')).toLocaleString('pt-BR')}`
    const d = document.createElement('div')
    d.textContent = r.descricao ?? ''
    txt.append(t, meta, d)
    if (r.analise) {
      const pre = document.createElement('pre')
      pre.textContent = JSON.stringify(r.analise, null, 2)
      txt.append(pre)
    }
    el.append(txt)
    return el
  }))
}

$('#form-login').addEventListener('submit', async e => {
  e.preventDefault()
  $('#erro-login').textContent = ''
  try {
    await api('login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: $('#email').value, senha: $('#senha').value }) })
    mostrar(true)
  } catch (err) { $('#erro-login').textContent = err.message }
})

$('#sair').addEventListener('click', async () => { await api('logout', { method: 'POST' }); mostrar(false) })

$('#foto').addEventListener('change', () => {
  const f = $('#foto').files[0]
  $('#previa').style.display = f ? 'block' : 'none'
  if (f) $('#previa').src = URL.createObjectURL(f)
})

$('#form-registro').addEventListener('submit', async e => {
  e.preventDefault()
  $('#erro-registro').textContent = ''
  $('#enviar').disabled = true
  try {
    const fd = new FormData()
    fd.append('titulo', $('#titulo').value)
    fd.append('descricao', $('#descricao').value)
    if ($('#foto').files[0]) fd.append('foto', $('#foto').files[0])
    await api('registros', { method: 'POST', body: fd })
    e.target.reset()
    $('#previa').style.display = 'none'
    carregar()
  } catch (err) { $('#erro-registro').textContent = err.message }
  $('#enviar').disabled = false
})

api('me').then(() => mostrar(true), () => mostrar(false))
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {})
