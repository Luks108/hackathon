// Página "Minha conta": dados, plano e telefones do WhatsApp com o estado de cada um.
(() => {
  'use strict'
  const { el, formatarTelefone, dataHora, nomesDosEntes } = window.U
  const $ = s => document.querySelector(s)
  const ATUALIZAR_MS = 10000     // o aprovado pelo administrador aparece sem recarregar a página
  const STATUS = {
    pendente: ['Aguardando aprovação', 'Um administrador ainda precisa aprovar este número.'],
    aprovado: ['Liberado', 'Este número já pode falar com o assistente no WhatsApp.'],
    revogado: ['Bloqueado', 'O administrador bloqueou este número.'],
  }

  let confirmando = null          // id do telefone que está esperando a confirmação de remoção
  let temporizador = null

  const mostrar = (id, sim) => { $(id).hidden = !sim }
  function mensagem(id, texto) { $(id).textContent = texto || ''; mostrar(id, !!texto) }
  function limparMensagens() { mensagem('#erro-tel', ''); mensagem('#ok-tel', '') }

  // ---------- dados e plano ----------
  function desenharDados(me) {
    $('#dado-nome').textContent = me.usuario.nome
    $('#dado-email').textContent = me.usuario.email
    $('#dado-plano').textContent = me.plano ? me.plano.nome : 'Sem plano ativo'
    $('#dado-entes').textContent = me.plano ? nomesDosEntes(me.plano.tenants) : 'Nada ainda: abra o assistente para ativar o acesso.'
  }

  // ---------- telefones ----------
  function itemDoTelefone(t) {
    const li = el('li', 'item')
    const [rotulo, explicacao] = STATUS[t.status] || [t.status, '']
    const principal = el('div', 'principal')
    principal.append(el('span', 'status ' + t.status, rotulo), el('div', 'numero', formatarTelefone(t.numero)), el('div', 'detalhe', explicacao))
    const criado = dataHora(t.criado_em)
    if (criado) principal.append(el('div', 'detalhe', 'Cadastrado em ' + criado))

    const acoes = el('div', 'acoes-item')
    const remover = el('button', 'botao pequeno perigo', confirmando === t.id ? 'Confirmar remoção' : 'Remover')
    remover.type = 'button'
    remover.setAttribute('aria-label', (confirmando === t.id ? 'Confirmar a remoção do telefone ' : 'Remover o telefone ') + formatarTelefone(t.numero))
    remover.addEventListener('click', () => removerTelefone(t, remover))
    acoes.append(remover)
    li.append(principal, acoes)
    return li
  }

  async function carregarTelefones() {
    let lista
    try {
      lista = await Api.telefones()
    } catch (e) {
      if (e.status === 401) { location.replace('chat.html'); return }
      mensagem('#erro-tel', e.message)
      return
    }
    // Não redesenha no meio de uma confirmação de remoção.
    if (confirmando === null) {
      $('#lista-tel').replaceChildren(...lista.map(itemDoTelefone))
      mostrar('#vazio-tel', lista.length === 0)
    }
  }

  async function removerTelefone(t, botao) {
    limparMensagens()
    if (confirmando !== t.id) {
      // Remover um número aprovado tira o acesso e exige nova aprovação: pede um segundo clique.
      confirmando = t.id
      botao.textContent = 'Confirmar remoção'
      setTimeout(() => { if (confirmando === t.id) { confirmando = null; botao.textContent = 'Remover' } }, 5000)
      return
    }
    botao.disabled = true
    try {
      await Api.removerTelefone(t.id)
      confirmando = null
      mensagem('#ok-tel', 'Telefone removido.')
    } catch (e) {
      confirmando = null
      mensagem('#erro-tel', e.message)
    }
    await carregarTelefones()
  }

  async function cadastrarTelefone(e) {
    e.preventDefault()
    limparMensagens()
    const campo = $('#tel-numero'), botao = $('#tel-enviar')
    if (!campo.value.trim()) { mensagem('#erro-tel', 'Informe o celular com DDD, como (87) 99999-9999.'); campo.focus(); return }
    botao.disabled = true
    try {
      const novo = await Api.cadastrarTelefone(campo.value)
      campo.value = ''
      mensagem('#ok-tel', `Telefone ${formatarTelefone(novo.numero)} cadastrado. Agora ele aguarda a aprovação de um administrador.`)
    } catch (e2) {
      mensagem('#erro-tel', e2.message)
    } finally {
      botao.disabled = false
    }
    await carregarTelefones()
  }

  // ---------- início ----------
  async function iniciar() {
    let me
    try {
      me = await Api.me()
    } catch (e) {
      $('#carregando').textContent = e.message
      return
    }
    if (!me.usuario) { location.replace('chat.html'); return }
    if (!me.plano) me.plano = await Api.garantirPlano()   // sem ele o cadastro de telefone é recusado
    Topo.montar(me.usuario, 'conta')
    desenharDados(me)
    mostrar('#carregando', false)
    mostrar('#pagina', true)
    await carregarTelefones()
    temporizador = setInterval(() => { if (document.visibilityState === 'visible') carregarTelefones() }, ATUALIZAR_MS)
  }

  $('#form-tel').addEventListener('submit', cadastrarTelefone)
  iniciar()
})()
