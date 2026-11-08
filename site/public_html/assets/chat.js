// Página do assistente: conta, plano e chat. Tudo que vem do servidor entra na tela por textContent,
// nunca por innerHTML, então um texto malicioso não executa nada.
(() => {
  'use strict'
  // Dentro do painel da página inicial, a página se ajusta ao espaço pequeno.
  if (/[?&]embutido\b/.test(location.search) || window.self !== window.top) document.documentElement.classList.add('embutido')
  const $ = s => document.querySelector(s)
  const ENTES = { 'pe-garanhuns': 'Município de Garanhuns', 'pe-estado': 'Estado de Pernambuco' }
  const ROTULOS = {
    cobertura: 'Verificando o que a base cobre',
    buscar_fornecedor: 'Procurando o fornecedor',
    listar_contratos: 'Listando contratos',
    buscar_contratos: 'Buscando contratos',
    execucao_do_fornecedor: 'Consultando valores pagos',
    contratos_do_fornecedor: 'Consultando os contratos do fornecedor',
    sancoes_do_fornecedor: 'Consultando sanções',
    conferir_evidencia: 'Conferindo a fonte',
  }
  const SUGESTOES = [
    'Quais contratos temos na base?',
    'Algum fornecedor tem sanção em aberto?',
    'A base de dados é completa?',
  ]
  // Demonstração livre: a conta nova não escolhe plano e recebe o plano único (Estado de Pernambuco e Garanhuns).
  // A regra de plano continua valendo no servidor. Ligue isto para voltar a pedir a escolha na tela.
  const ESCOLHER_PLANO = false
  const INTERVALO_MS = 700          // o plano pede leitura a cada 0,7 s
  const LIMITE_MS = 130000          // RF-14: depois disso, mensagem legível
  const ESTADOS_FINAIS = ['concluida', 'erro']

  const estado = { usuario: null, plano: null, acompanhando: false, sessao: 0 }

  const esperar = ms => new Promise(r => setTimeout(r, ms))
  const el = (tag, classe, texto) => {
    const e = document.createElement(tag)
    if (classe) e.className = classe
    if (texto !== undefined) e.textContent = texto
    return e
  }
  const mostrar = (id, sim) => { $(id).hidden = !sim }
  const nomeDoEnte = id => ENTES[id] || id
  const dinheiro = n => n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 0 })

  // ---------- telas ----------
  function tela(nome) {
    for (const t of ['carregando', 'entrar', 'plano', 'chat']) mostrar('#tela-' + t, t === nome)
    document.body.classList.toggle('modo-chat', nome === 'chat')
    mostrar('#topo-acoes', !!estado.usuario)
    mostrar('#topo-links', !!estado.usuario)
    $('#link-admin').hidden = !(estado.usuario && estado.usuario.papel === 'admin')
    if (estado.usuario) $('#quem').textContent = estado.usuario.nome + (ESCOLHER_PLANO && estado.plano ? ' · plano ' + estado.plano.nome : '')
  }

  function erroEm(id, mensagem) {
    const e = $(id)
    e.textContent = mensagem || ''
    e.hidden = !mensagem
  }

  function aplicarConta(dados) {
    estado.usuario = dados.usuario || null
    estado.plano = dados.plano || null
  }

  async function decidirTela() {
    if (!estado.usuario) { tela('entrar'); return }
    if (!estado.plano) {
      if (!ESCOLHER_PLANO && await ativarPlanoPadrao()) { await abrirChat(); return }
      await mostrarPlanos()   // escolha manual, ou saída de emergência se a ativação automática falhar
      return
    }
    await abrirChat()
  }

  // Sem pedir nada, a conta recebe o plano único. Se algo falhar, cai na escolha manual.
  async function ativarPlanoPadrao() {
    const plano = await Api.garantirPlano()
    if (!plano) return false
    estado.plano = plano
    return true
  }

  // ---------- plano no chat ----------
  function mostrarPlanoAtual() {
    $('#plano-info').textContent = 'Consulta: ' + estado.plano.tenants.map(nomeDoEnte).join(' e ')
  }

  // ---------- entrar e criar conta ----------
  function trocarAba(qual) {
    const entrar = qual === 'entrar'
    $('#aba-entrar').setAttribute('aria-selected', String(entrar))
    $('#aba-cadastro').setAttribute('aria-selected', String(!entrar))
    mostrar('#form-entrar', entrar)
    mostrar('#form-cadastro', !entrar)
    erroEm('#erro-entrar', ''); erroEm('#erro-cadastro', '')
  }

  async function enviarForm(form, botaoTexto, erroId, acao) {
    const botao = form.querySelector('button[type=submit]')
    erroEm(erroId, '')
    botao.disabled = true
    try {
      aplicarConta(await acao())
      form.reset()
      await decidirTela()
    } catch (e) {
      erroEm(erroId, e.message)
    } finally {
      botao.disabled = false
    }
  }

  // ---------- planos ----------
  async function mostrarPlanos() {
    tela('plano')
    erroEm('#erro-plano', '')
    const lista = $('#lista-planos')
    lista.replaceChildren()
    try {
      const planos = await Api.planos()
      for (const p of planos) {
        const cartao = el('div', 'plano')
        cartao.append(el('h3', '', p.nome))
        const preco = el('p', 'preco', dinheiro(p.preco_mensal) + ' ')
        preco.append(el('small', '', '/ mês'))
        cartao.append(preco)
        const ul = el('ul')
        if (p.franquia > 0) ul.append(el('li', '', p.franquia.toLocaleString('pt-BR') + ' perguntas por mês'))
        if (p.preco_excedente > 0) ul.append(el('li', '', 'Excedente: ' + p.preco_excedente.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) + ' por pergunta'))
        ul.append(el('li', '', 'Consulta: ' + p.tenants.map(nomeDoEnte).join(' e ')))
        cartao.append(ul)
        const b = el('button', 'botao cheio', 'Ativar plano de demonstração')
        b.type = 'button'
        b.addEventListener('click', () => ativarPlano(p.id, b))
        cartao.append(b)
        lista.append(cartao)
      }
    } catch (e) {
      erroEm('#erro-plano', e.message)
    }
  }

  async function ativarPlano(id, botao) {
    erroEm('#erro-plano', '')
    botao.disabled = true
    try {
      const r = await Api.ativarPlano(id)
      estado.plano = r.plano
      await abrirChat()
    } catch (e) {
      erroEm('#erro-plano', e.message)
      botao.disabled = false
    }
  }

  // ---------- chat ----------
  function boasVindas() {
    const conversa = $('#conversa')
    conversa.replaceChildren()
    const w = el('div', 'boas-vindas')
    w.append(el('h2', '', 'Como posso ajudar?'))
    w.append(el('p', 'apoio', 'Pergunte sobre fornecedores. Cada resposta traz a fonte, com o trecho do portal.'))
    const lista = el('div', 'sugestoes')
    for (const s of SUGESTOES) {
      const b = el('button', 'sugestao', s)
      b.type = 'button'
      b.addEventListener('click', () => { $('#pergunta').value = s; atualizarContador(); enviarPergunta() })
      lista.append(b)
    }
    w.append(lista)
    conversa.append(w)
  }

  async function abrirChat() {
    tela('chat')
    mostrarPlanoAtual()
    travarEntrada(false)
    boasVindas()
    atualizarContador()
    // Se a pergunta anterior ainda está em andamento (a página foi recarregada), volta a acompanhá-la.
    try {
      const { pergunta } = await Api.perguntaAberta()
      if (pergunta) { retomar(pergunta); return }
    } catch (e) {
      if (e.status === 401) { estado.usuario = null; tela('entrar') }
    }
    $('#pergunta').focus()
  }

  function noFim(conversa) {
    return conversa.scrollHeight - conversa.scrollTop - conversa.clientHeight < 80
  }

  function adicionarPergunta(texto) {
    const conversa = $('#conversa')
    conversa.querySelector('.boas-vindas')?.remove()
    conversa.append(el('div', 'msg eu', texto))
    conversa.scrollTop = conversa.scrollHeight
  }

  function criarResposta() {
    const raiz = el('div', 'msg bot')
    const progresso = el('div', 'progresso')
    const pontos = el('span', 'pontos'); pontos.append(el('i'), el('i'), el('i'))
    const rotulo = el('span', '', 'Enviando sua pergunta…')
    progresso.append(pontos, rotulo)
    const texto = el('div', 'texto-resp')
    const fontes = el('div', 'fontes')
    raiz.append(progresso, texto, fontes)
    $('#conversa').append(raiz)
    return { raiz, progresso, rotulo, texto, fontes, nFontes: 0 }
  }

  const dataBR = iso => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? `${m[3]}/${m[2]}/${m[1]}` : '' }
  const urlSegura = u => (typeof u === 'string' && /^https?:\/\//i.test(u)) ? u : null   // nunca javascript:

  function adicionarFonte(resp, d) {
    resp.nFontes++
    const det = el('details', 'fonte')
    det.append(el('summary', '', resp.nFontes === 1 && !resp.fontes.children.length ? 'Ver fonte' : 'Ver fonte ' + resp.nFontes))
    det.append(el('blockquote', '', String(d.trecho || 'Trecho não informado.')))
    const meta = el('small', 'meta')
    const partes = []
    if (d.capturado_em) partes.push('Capturado em ' + dataBR(String(d.capturado_em)))
    if (d.evidencia) partes.push('evidência ' + d.evidencia)
    meta.append(partes.join(' · '))
    const url = urlSegura(d.url)
    if (url) {
      if (partes.length) meta.append(' · ')
      const a = el('a', '', 'Abrir no portal')
      a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'
      meta.append(a)
    }
    det.append(meta)
    resp.fontes.append(det)
  }

  function aplicarEvento(ev, resp) {
    const d = ev.dados || {}
    switch (ev.tipo) {
      case 'consulta': {
        const nome = String(d.nome || '').replace(/^mcp__transparencia__/, '')
        resp.rotulo.textContent = (ROTULOS[nome] || 'Consultando a base') + '…'
        break
      }
      case 'texto':
        if (typeof d.delta === 'string') resp.texto.textContent += d.delta
        break
      case 'fonte':
        adicionarFonte(resp, d)
        break
      case 'fim':
        resp.progresso.hidden = true
        break
      case 'erro':
        resp.progresso.hidden = true
        resp.raiz.append(el('p', 'erro-resp', typeof d.motivo === 'string' && d.motivo ? d.motivo : 'Não consegui concluir a consulta. Tente novamente.'))
        break
    }
  }

  function travarEntrada(travada) {
    $('#pergunta').disabled = travada
    $('#enviar').disabled = travada
    document.querySelectorAll('.sugestao').forEach(b => { b.disabled = travada })
  }

  async function acompanhar(id) {
    const sessao = estado.sessao
    const resp = criarResposta()
    estado.acompanhando = true
    travarEntrada(true)
    const conversa = $('#conversa')
    const inicio = Date.now()
    let desde = 0, falhas = 0, terminou = false
    try {
      while (!terminou && sessao === estado.sessao) {
        if (Date.now() - inicio > LIMITE_MS) {
          aplicarEvento({ tipo: 'erro', dados: { motivo: 'A consulta demorou mais que o esperado. Tente novamente.' } }, resp)
          break
        }
        let dados
        try {
          dados = await Api.eventos(id, desde)
          falhas = 0
        } catch (e) {
          if (e.status === 401) { estado.usuario = null; tela('entrar'); return }
          if (e.status === 404) {
            aplicarEvento({ tipo: 'erro', dados: { motivo: 'Não encontrei essa pergunta. Tente novamente.' } }, resp)
            break
          }
          if (++falhas >= 5) {
            aplicarEvento({ tipo: 'erro', dados: { motivo: 'Perdi a conexão com o serviço. Tente novamente.' } }, resp)
            break
          }
          await esperar(INTERVALO_MS * falhas)
          continue
        }
        if (dados.status === 'fila' && dados.fila > 1) resp.rotulo.textContent = `Você é o ${dados.fila}º da fila…`
        else if (dados.status === 'processando' && !dados.eventos.length && resp.rotulo.textContent.includes('da fila')) resp.rotulo.textContent = 'Consultando a base…'
        const seguir = noFim(conversa)
        for (const ev of dados.eventos) {
          desde = ev.seq
          aplicarEvento(ev, resp)
          if (ev.tipo === 'fim' || ev.tipo === 'erro') terminou = true
        }
        if (ESTADOS_FINAIS.includes(dados.status)) {
          terminou = true
          if (!dados.eventos.some(e => e.tipo === 'fim' || e.tipo === 'erro')) resp.progresso.hidden = true
        }
        if (seguir) conversa.scrollTop = conversa.scrollHeight
        if (!terminou) await esperar(INTERVALO_MS)   // para de consultar assim que termina
      }
    } finally {
      estado.acompanhando = false
      resp.progresso.hidden = true
      if (sessao === estado.sessao) { travarEntrada(false); $('#pergunta').focus() }
    }
  }

  function retomar(pergunta) {
    $('#conversa').replaceChildren()
    adicionarPergunta(pergunta.texto)
    acompanhar(pergunta.id)
  }

  async function enviarPergunta() {
    if (estado.acompanhando) return
    const campo = $('#pergunta')
    const texto = campo.value.trim()
    if (!texto) return
    travarEntrada(true)
    try {
      const { id } = await Api.perguntar(texto)
      campo.value = ''
      atualizarContador()
      adicionarPergunta(texto)
      acompanhar(id)
    } catch (e) {
      travarEntrada(false)
      if (e.status === 401) { estado.usuario = null; tela('entrar'); return }
      if (e.status === 403 && /plano/i.test(e.message)) { estado.plano = null; await decidirTela(); return }
      if (e.status === 409 && e.dados && e.dados.pergunta_id) {
        // já havia uma em andamento: mostra e continua acompanhando
        const { pergunta } = await Api.perguntaAberta()
        if (pergunta) { retomar(pergunta); return }
      }
      const conversa = $('#conversa')
      conversa.querySelector('.boas-vindas')?.remove()
      const aviso = el('p', 'aviso-erro', e.message)
      aviso.setAttribute('role', 'alert')
      conversa.append(aviso)
      conversa.scrollTop = conversa.scrollHeight
    }
  }

  function atualizarContador() {
    const campo = $('#pergunta')
    const n = campo.value.length
    const c = $('#contador')
    c.textContent = n + '/500'
    c.classList.toggle('perto', n >= 450)
    campo.style.height = 'auto'
    campo.style.height = Math.min(campo.scrollHeight, 150) + 'px'
  }

  // ---------- eventos ----------
  $('#aba-entrar').addEventListener('click', () => trocarAba('entrar'))
  $('#aba-cadastro').addEventListener('click', () => trocarAba('cadastro'))

  $('#form-entrar').addEventListener('submit', e => {
    e.preventDefault()
    enviarForm(e.target, 'Entrar', '#erro-entrar', () => Api.entrar($('#entrar-email').value, $('#entrar-senha').value))
  })
  $('#form-cadastro').addEventListener('submit', e => {
    e.preventDefault()
    enviarForm(e.target, 'Criar conta', '#erro-cadastro', () => Api.cadastrar($('#cad-nome').value, $('#cad-email').value, $('#cad-senha').value))
  })

  $('#sair').addEventListener('click', async () => {
    estado.sessao++   // interrompe qualquer acompanhamento em andamento
    try { await Api.sair() } catch { /* sai mesmo assim */ }
    estado.usuario = null; estado.plano = null
    tela('entrar')
    trocarAba('entrar')
  })

  $('#form-pergunta').addEventListener('submit', e => { e.preventDefault(); enviarPergunta() })
  $('#pergunta').addEventListener('input', atualizarContador)
  $('#pergunta').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); enviarPergunta() }
  })

  // ---------- início ----------
  Api.me().then(aplicarConta).then(decidirTela).catch(e => {
    tela('entrar')
    erroEm('#erro-entrar', e.message)
  })
})()
