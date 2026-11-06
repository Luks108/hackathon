// Administração: fila de telefones do WhatsApp. Aprovar e bloquear são um clique cada.
// Quem não é administrador só vê um aviso. O servidor recusa as rotas de qualquer jeito (403).
(() => {
  'use strict'
  const { el, formatarTelefone, dataHora } = window.U
  const $ = s => document.querySelector(s)
  const ATUALIZAR_MS = 15000
  const VAZIO = {
    pendente: 'Nenhum telefone aguardando aprovação.',
    aprovado: 'Nenhum telefone aprovado ainda.',
    revogado: 'Nenhum telefone bloqueado.',
    todos: 'Nenhum telefone cadastrado ainda.',
  }
  const ROTULO = { pendente: 'Aguardando', aprovado: 'Aprovado', revogado: 'Bloqueado' }

  let filtro = 'pendente'
  let ocupado = false              // há uma decisão em andamento: não redesenha por cima dela
  const mostrar = (id, sim) => { $(id).hidden = !sim }
  function mensagem(id, texto) { $(id).textContent = texto || ''; mostrar(id, !!texto) }

  function botao(texto, classe, aoClicar, rotuloAcessivel) {
    const b = el('button', 'botao pequeno ' + classe, texto)
    b.type = 'button'
    b.setAttribute('aria-label', rotuloAcessivel)
    b.addEventListener('click', aoClicar)
    return b
  }

  function itemDoTelefone(t) {
    const li = el('li', 'item')
    const numero = formatarTelefone(t.numero)
    const principal = el('div', 'principal')
    principal.append(el('span', 'status ' + t.status, ROTULO[t.status] || t.status), el('div', 'numero', numero))
    principal.append(el('div', 'detalhe', `${t.usuario.nome} · ${t.usuario.email}`))
    principal.append(el('div', 'detalhe', 'Plano: ' + (t.usuario.plano || 'sem plano ativo') + ' · cadastrado em ' + dataHora(t.criado_em)))
    if (t.decidido_por) principal.append(el('div', 'detalhe', `Última decisão: ${t.decidido_por.nome} em ${dataHora(t.atualizado_em)}`))

    const acoes = el('div', 'acoes-item')
    if (t.status === 'pendente') {
      acoes.append(botao('Aprovar', '', () => decidir(t, 'aprovar'), 'Aprovar o telefone ' + numero))
      acoes.append(botao('Recusar', 'perigo', () => decidir(t, 'revogar'), 'Recusar o telefone ' + numero))
    } else if (t.status === 'aprovado') {
      acoes.append(botao('Bloquear', 'perigo', () => decidir(t, 'revogar'), 'Bloquear o telefone ' + numero))
    } else {
      acoes.append(botao('Aprovar de novo', '', () => decidir(t, 'aprovar'), 'Aprovar de novo o telefone ' + numero))
    }
    li.append(principal, acoes)
    return li
  }

  async function carregar() {
    if (ocupado) return
    let lista
    try {
      lista = await Api.adminTelefones(filtro)
    } catch (e) {
      if (e.status === 401) { location.replace('chat.html'); return }
      mensagem('#erro-adm', e.message)
      return
    }
    if (ocupado) return
    mensagem('#erro-adm', '')
    $('#lista-adm').replaceChildren(...lista.map(itemDoTelefone))
    $('#vazio-adm').textContent = VAZIO[filtro]
    mostrar('#vazio-adm', lista.length === 0)
    $('#atualizado').textContent = 'Atualizado às ' + new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  async function decidir(t, acao) {
    ocupado = true
    document.querySelectorAll('#lista-adm button').forEach(b => { b.disabled = true })
    mensagem('#ok-adm', ''); mensagem('#erro-adm', '')
    const numero = formatarTelefone(t.numero)
    try {
      if (acao === 'aprovar') await Api.aprovarTelefone(t.id)
      else await Api.revogarTelefone(t.id)
      mensagem('#ok-adm', acao === 'aprovar' ? `Telefone ${numero} aprovado.` : `Telefone ${numero} bloqueado.`)
    } catch (e) {
      mensagem('#erro-adm', e.message)
    } finally {
      ocupado = false
    }
    await carregar()
  }

  function trocarFiltro(novo) {
    filtro = novo
    document.querySelectorAll('.filtros [role=tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.status === novo)))
    mensagem('#ok-adm', '')
    carregar()
  }

  async function iniciar() {
    let me
    try {
      me = await Api.me()
    } catch (e) {
      $('#carregando').textContent = e.message
      return
    }
    if (!me.usuario) { location.replace('chat.html'); return }
    Topo.montar(me.usuario, 'admin')
    mostrar('#carregando', false)
    if (me.usuario.papel !== 'admin') { mostrar('#acesso-negado', true); return }
    mostrar('#pagina', true)
    document.querySelectorAll('.filtros [role=tab]').forEach(b => b.addEventListener('click', () => trocarFiltro(b.dataset.status)))
    await carregar()
    setInterval(() => { if (document.visibilityState === 'visible') carregar() }, ATUALIZAR_MS)
  }

  iniciar()
})()
