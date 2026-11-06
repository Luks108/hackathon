// Área técnica. O conteúdo vem de /api/painel, que exige login.
// O texto das seções é nosso. Tudo que vem dos dados entra por textContent, nunca como HTML.
(() => {
  'use strict'
  const { el } = window.U
  const $ = s => document.querySelector(s)
  const ABAS = [['arquitetura', 'Arquitetura'], ['dados', 'Dados'], ['ontologia', 'Ontologia'], ['grafo', 'Grafo'], ['negocio', 'Modelo de negócios'],
    ['benchmark', 'Benchmark'], ['carga', 'Teste de carga'], ['seguranca', 'Segurança']]
  const TIPOS = { fato: 'Fato', ausencia: 'Ausência', isolamento: 'Isolamento', ataque: 'Ataque' }

  function numero(raiz, valor, rotulo) {
    const c = el('div', 'numero-painel')
    c.append(el('b', '', valor), el('span', '', rotulo))
    raiz.append(c)
  }

  function linha(celulas, tag = 'td') {
    const tr = el('tr')
    for (const c of celulas) {
      const td = el(tag, c && c.classe ? c.classe : '')
      if (c && c.no) td.append(c.no)
      else td.textContent = c && c.texto !== undefined ? c.texto : c
      tr.append(td)
    }
    return tr
  }

  function tabela(raiz, cabecalho) {
    const thead = el('thead'), tbody = el('tbody')
    thead.append(linha(cabecalho, 'th'))
    raiz.replaceChildren(thead, tbody)
    return tbody
  }

  // ---------- benchmark ----------
  function desenharBenchmark(b) {
    const a = b.linhas.filter(l => l.braco === 'fornexia')
    const s = b.linhas.filter(l => l.braco === 'sem_base')
    const soma = ls => ls.reduce((n, l) => n + l.nota, 0)
    const fatos = a.filter(l => l.tipo === 'fato')
    const defesa = a.filter(l => l.tipo !== 'fato')
    const media = a.reduce((n, l) => n + l.total_s, 0) / a.length
    const q = $('#numeros-bench')
    numero(q, `${soma(a)}/${a.length}`, 'FornexIA, nota total')
    numero(q, `${soma(s)}/${s.length}`, 'Modelo sem acesso aos dados')
    numero(q, `${fatos.filter(l => l.provada).length}/${fatos.length}`, 'Fatos com evidência conferida')
    numero(q, `${soma(defesa)}/${defesa.length}`, 'Isolamento e ataques')
    numero(q, `${media.toFixed(1).replace('.', ',')} s`, 'Tempo médio por resposta')

    const corpo = tabela($('#tabela-bench'), ['Pergunta', 'Tipo', 'Perfil', 'Nota', 'Sem dados', 'Evidências', 'Tempo', ''])
    for (const l of a) {
      const semDados = s.find(x => x.id === l.id)
      const ver = el('button', '', 'Ver resposta')
      ver.type = 'button'
      const tr = linha([
        l.pergunta, TIPOS[l.tipo] || l.tipo, l.perfil === 'estado' ? 'Estado' : 'Município',
        { texto: l.nota ? 'Passou' : 'Não passou', classe: l.nota ? 'nota-ok' : 'nota-nao' },
        semDados ? (semDados.nota ? 'Passou' : 'Não passou') : '—',
        { texto: String(l.fontes), classe: 'num' }, { texto: `${l.total_s} s`.replace('.', ','), classe: 'num' }, { no: ver },
      ])
      const detalhe = el('tr')
      const td = el('td', 'resposta-bench', l.resposta)
      td.colSpan = 8
      detalhe.append(td)
      detalhe.hidden = true
      ver.addEventListener('click', () => {
        detalhe.hidden = !detalhe.hidden
        ver.textContent = detalhe.hidden ? 'Ver resposta' : 'Ocultar'
      })
      corpo.append(tr, detalhe)
    }
    $('#rodape-bench').textContent = `Modelo ${b.modelo}. Gabarito ${b.gabarito}. Rodada de ${b.em.slice(8, 10)}/${b.em.slice(5, 7)}/${b.em.slice(0, 4)}.`
  }

  // ---------- dados ----------
  function desenharDados(inventario, ex) {
    const corpo = tabela($('#tabela-inventario'), ['Fonte', 'Formato', 'Tamanho', 'Volume', 'Situação'])
    for (const i of inventario) {
      corpo.append(linha([i.nome, i.formato, { texto: i.tamanho, classe: 'num' }, i.volume, { no: el('span', 'selo ' + i.selo, i.estado) }]))
    }
    const json = v => JSON.stringify(v, null, 2)
    $('#cru-contrato').textContent = ex.cru_contrato
    $('#cru-sancao').textContent = ex.cru_sancao
    $('#fato-contrato').textContent = json(ex.fato_contrato)
    $('#fato-sancao').textContent = json(ex.fato_sancao)
    $('#fato-evidencia').textContent = json(ex.evidencia)
    $('#cru-estado').textContent = ex.cru_estado
    $('#fato-contrato-estado').textContent = json(ex.fato_contrato_estado)
    $('#fato-execucao').textContent = json(ex.fato_execucao)
    $('#caminho-grafo').textContent = ex.caminho.join('\n')
  }

  // ---------- teste de carga ----------
  function desenharCarga(c) {
    const f = n => String(n).replace('.', ',')
    const q = $('#numeros-carga')
    numero(q, `${c.pessoas - c.erros_usuario}/${c.pessoas}`, 'Respostas concluídas')
    numero(q, `${f(c.duracao_s)} s`, 'Para atender as 8')
    numero(q, `${f(c.latencia_media_s)} s`, 'Tempo médio de cada requisição')
    numero(q, `${c.erros_500} em ${c.requisicoes}`, 'Erro 500, sem efeito para o usuário')
    numero(q, `${c.memoria_extra_mb} MB`, 'Memória extra no notebook')
    const corpo = tabela($('#tabela-carga'), ['Pessoa', 'Saiu da fila', 'Primeiro sinal', 'Resposta completa', 'Evidências'])
    for (const l of c.linhas) {
      corpo.append(linha([l.pessoa, { texto: `${f(l.inicio)} s`, classe: 'num' }, { texto: `${f(l.primeiro)} s`, classe: 'num' },
        { texto: `${f(l.total)} s`, classe: 'num' }, { texto: String(l.fontes), classe: 'num' }]))
    }
    $('#rodape-carga').textContent = `Rodada de ${c.em.slice(8, 10)}/${c.em.slice(5, 7)}/${c.em.slice(0, 4)}, com ${c.agentes_site} agentes no site.`
  }

  // ---------- grafo ----------
  const CORES = { Contrato: '#3f7fc2', Fornecedor: '#23845f', Sancao: '#c2603f', ProcessoLicitatorio: '#8a2ca8',
    UnidadeJurisdicionada: '#b5801f', Ente: '#0b2545', Evidencia: '#9a978b', ExecucaoFinanceira: '#2a8c8c' }
  const NOMES = { Contrato: 'Contrato', Fornecedor: 'Fornecedor', Sancao: 'Sanção', ProcessoLicitatorio: 'Processo',
    UnidadeJurisdicionada: 'Unidade', Ente: 'Ente público', Evidencia: 'Evidência', ExecucaoFinanceira: 'Execução financeira' }
  const RAIOS = { Ente: 15, Fornecedor: 11, Contrato: 9, ProcessoLicitatorio: 8, UnidadeJurisdicionada: 8, Sancao: 6, Evidencia: 4, ExecucaoFinanceira: 5 }
  const PLURAIS = { Contrato: 'Contratos', Fornecedor: 'Fornecedores', Sancao: 'Sanções', ProcessoLicitatorio: 'Processos',
    UnidadeJurisdicionada: 'Unidades', Ente: 'Entes públicos', Evidencia: 'Evidências', ExecucaoFinanceira: 'Execuções' }
  const dataBR = iso => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? `${m[3]}/${m[2]}/${m[1]}` : '' }
  // Várias ocorrências têm o mesmo tipo: a situação e a data dizem qual é qual.
  const rotuloDe = n => n.t === 'Sancao'
    ? [n.r, n.p.situacao === 'EM ABERTO' ? 'em aberto' : 'liberada', dataBR(n.p.publicada_em)].filter(Boolean).join(' · ')
    : n.r
  const brl = v => Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

  function campos(n) {
    const p = n.p, l = []
    const c = (r, v) => { if (v !== null && v !== undefined && v !== '') l.push([r, v]) }
    if (n.t === 'Contrato') { c('Valor contratado', brl(p.valor_contratado)); c('Vigência', [p.inicio, p.fim].filter(Boolean).join(' a ')); c('Objeto', p.objeto) }
    else if (n.t === 'Fornecedor') { c('CNPJ', p.cnpj); c('Identidade', p.resolvido ? 'Confirmada por documento' : 'Sem documento completo') }
    else if (n.t === 'Sancao') { c('Tipo', p.tipo); c('Situação', p.situacao); c('Órgão', p.orgao); c('Publicada em', p.publicada_em); c('Fim da suspensão', p.fim_suspensao); c('Descrição', p.descricao) }
    else if (n.t === 'ProcessoLicitatorio') { c('Número', p.numero); c('Modalidade', p.modalidade); c('Fase', p.fase); if (p.valor_estimado != null) c('Valor estimado', brl(p.valor_estimado)) }
    else if (n.t === 'ExecucaoFinanceira') { c('Ano', p.ano); c('Órgão', p.orgao); c('Empenhado', brl(p.empenhado)); c('Liquidado', brl(p.liquidado)); c('Pago', brl(p.pago)); c('Restos a pagar', brl(p.restos_a_pagar)) }
    else if (n.t === 'Ente') { c('Esfera', p.esfera); c('UF', p.uf) }
    else if (n.t === 'Evidencia') { c('Trecho', p.trecho); c('Tabela e linha', `${p.tabela}, linha ${p.linha}`); c('Hash do arquivo', p.documento_hash); c('Capturado em', p.capturado_em) }
    return l
  }

  function criarGrafo(dados) {
    const tela = $('#tela-grafo'), ctx = tela.getContext('2d')
    const visiveis = {}
    Object.keys(CORES).forEach(t => { visiveis[t] = t !== 'Evidencia' && t !== 'ExecucaoFinanceira' })
    const nos = dados.nos.map(n => ({ ...n, x: 0, y: 0, vx: 0, vy: 0 }))
    const porId = Object.fromEntries(nos.map(n => [n.id, n]))
    const arestas = dados.arestas.filter(e => porId[e.a] && porId[e.b]).map(e => ({ a: porId[e.a], b: porId[e.b], rel: e.rel }))
    let L = 800, A = 540, escala = 1, selecionado = null, preso = null, quadros = 0, rodando = false
    const ativo = n => visiveis[n.t]

    function medir() {
      const r = tela.getBoundingClientRect()
      L = r.width || 800; A = r.height || 540; escala = window.devicePixelRatio || 1
      tela.width = L * escala; tela.height = A * escala
    }
    function passo() {
      const vivos = nos.filter(ativo)
      for (let i = 0; i < vivos.length; i++) for (let j = i + 1; j < vivos.length; j++) {
        const a = vivos[i], b = vivos[j]
        let dx = a.x - b.x, dy = a.y - b.y
        const d2 = dx * dx + dy * dy + 0.01
        if (d2 > 90000) continue
        const f = 2600 / d2, d = Math.sqrt(d2)
        dx *= f / d; dy *= f / d
        a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy
      }
      for (const e of arestas) {
        if (!ativo(e.a) || !ativo(e.b)) continue
        let dx = e.b.x - e.a.x, dy = e.b.y - e.a.y
        const d = Math.sqrt(dx * dx + dy * dy) || 1
        const f = (d - (e.rel === 'PROVADO_POR' ? 34 : e.rel === 'RECEBEU' ? 46 : 92)) * 0.02
        dx *= f / d; dy *= f / d
        e.a.vx += dx; e.a.vy += dy; e.b.vx -= dx; e.b.vy -= dy
      }
      for (const n of vivos) {
        n.vx = (n.vx + (L / 2 - n.x) * 0.004) * 0.82
        n.vy = (n.vy + (A / 2 - n.y) * 0.006) * 0.82
        if (n !== preso) { n.x += n.vx; n.y += n.vy }
        n.x = Math.max(26, Math.min(L - 26, n.x)); n.y = Math.max(22, Math.min(A - 22, n.y))
      }
    }
    function desenhar() {
      const viz = new Set()
      if (selecionado) for (const e of arestas) { if (e.a === selecionado) viz.add(e.b); if (e.b === selecionado) viz.add(e.a) }
      ctx.setTransform(escala, 0, 0, escala, 0, 0)
      ctx.clearRect(0, 0, L, A)
      for (const e of arestas) {
        if (!ativo(e.a) || !ativo(e.b)) continue
        const perto = selecionado && (e.a === selecionado || e.b === selecionado)
        ctx.globalAlpha = selecionado ? (perto ? 0.9 : 0.1) : 0.34
        ctx.strokeStyle = perto ? '#0b2545' : '#5d6c80'
        ctx.lineWidth = perto ? 1.5 : 1
        ctx.beginPath(); ctx.moveTo(e.a.x, e.a.y); ctx.lineTo(e.b.x, e.b.y); ctx.stroke()
      }
      for (const n of nos.filter(ativo)) {
        ctx.globalAlpha = !selecionado || n === selecionado || viz.has(n) ? 1 : 0.2
        ctx.beginPath(); ctx.arc(n.x, n.y, RAIOS[n.t], 0, 6.2832); ctx.fillStyle = CORES[n.t]; ctx.fill()
        if (n === selecionado) { ctx.lineWidth = 2.5; ctx.strokeStyle = '#0b2545'; ctx.stroke() }
      }
      ctx.font = "12px 'IBM Plex Mono', Consolas, monospace"
      ctx.textAlign = 'center'
      ctx.lineJoin = 'round'
      for (const n of nos.filter(ativo)) {
        if (selecionado ? !(n === selecionado || viz.has(n)) : !(n.t === 'Ente' || n.t === 'Fornecedor')) continue
        const t = n.r.length > 26 ? n.r.slice(0, 25) + '…' : n.r
        const y = n.y + RAIOS[n.t] + 14
        ctx.globalAlpha = 1; ctx.lineWidth = 3.5; ctx.strokeStyle = '#ffffff'
        ctx.strokeText(t, n.x, y); ctx.fillStyle = '#14263f'; ctx.fillText(t, n.x, y)
      }
      ctx.globalAlpha = 1
    }
    function laco() {
      if (quadros > 0) { passo(); desenhar(); quadros--; requestAnimationFrame(laco) } else { rodando = false; desenhar() }
    }
    function agitar(q) {
      quadros = Math.max(quadros, q)
      if (!rodando) { rodando = true; requestAnimationFrame(laco) }
    }
    function detalhar(n) {
      selecionado = n
      desenhar()
      const d = $('#detalhe-grafo')
      d.replaceChildren()
      if (!n) {
        d.append(el('h3', '', 'Clique em um ponto'), el('p', '', 'Ative Evidência na legenda para ver todas as provas no grafo.'))
        return
      }
      d.append(el('span', 'apoio', NOMES[n.t]), el('h3', '', n.r))
      const dl = el('dl')
      for (const [r, v] of campos(n)) {
        const b = el('div')
        b.append(el('dt', '', r), el('dd', r === 'Trecho' ? 'trecho' : '', String(v)))
        dl.append(b)
      }
      d.append(dl)
      if (n.t === 'Evidencia' && /^https:\/\//.test(n.p.url || '')) {
        const a = el('a', '', 'Abrir a fonte')
        a.href = n.p.url; a.target = '_blank'; a.rel = 'noopener noreferrer'
        d.append(a)
      }
      // Ligações agrupadas por tipo do outro ponto, cada uma com um rótulo que a distingue.
      const grupos = new Map()
      for (const e of arestas) {
        const outro = e.a === n ? e.b : e.b === n ? e.a : null
        if (!outro) continue
        if (!grupos.has(outro.t)) grupos.set(outro.t, new Map())
        grupos.get(outro.t).set(outro.id, outro)
      }
      for (const [tipo, itens] of grupos) {
        const caixa = el('details', 'grupo-grafo')
        caixa.open = itens.size <= 5
        caixa.append(el('summary', '', `${PLURAIS[tipo]} (${itens.size})`))
        for (const outro of [...itens.values()].sort((a, b) => rotuloDe(a).localeCompare(rotuloDe(b), 'pt-BR'))) {
          const b = el('button', 'item-grafo', rotuloDe(outro))
          b.type = 'button'
          b.addEventListener('click', () => { if (!visiveis[outro.t]) ligar(outro.t, true); detalhar(outro) })
          caixa.append(b)
        }
        d.append(caixa)
      }
    }
    function ligar(tipo, valor) {
      visiveis[tipo] = valor
      const c = document.getElementById('t-' + tipo)
      if (c) c.checked = valor
      agitar(90)
    }
    const ponto = ev => { const r = tela.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top } }
    function achar(p) {
      let melhor = null, dist = 1e9
      for (const n of nos.filter(ativo)) {
        const d = Math.hypot(n.x - p.x, n.y - p.y)
        if (d < RAIOS[n.t] + 8 && d < dist) { dist = d; melhor = n }
      }
      return melhor
    }
    tela.addEventListener('pointerdown', ev => {
      const n = achar(ponto(ev))
      detalhar(n)
      if (n) { preso = n; try { tela.setPointerCapture(ev.pointerId) } catch { /* sem captura, segue */ } }
    })
    tela.addEventListener('pointermove', ev => {
      if (!preso) return
      const p = ponto(ev)
      preso.x = p.x; preso.y = p.y
      agitar(30)
    })
    tela.addEventListener('pointerup', () => { preso = null })
    tela.addEventListener('pointercancel', () => { preso = null })

    const contagem = {}
    for (const n of nos) contagem[n.t] = (contagem[n.t] || 0) + 1
    const legenda = $('#legenda-grafo')
    for (const t of Object.keys(CORES)) {
      if (!contagem[t]) continue
      const r = el('label'), c = el('input'), p = el('span', 'pino')
      c.type = 'checkbox'; c.id = 't-' + t; c.checked = visiveis[t]
      p.style.background = CORES[t]
      c.addEventListener('change', () => { if (selecionado && selecionado.t === t && !c.checked) detalhar(null); ligar(t, c.checked) })
      r.append(c, p, `${NOMES[t]} ${contagem[t]}`)
      legenda.append(r)
    }
    return {
      abrir() {
        medir()
        if (nos.every(n => n.x === 0)) {
          nos.forEach((n, i) => { const a = i * 2.399963, r = 40 + 39 * Math.sqrt(i); n.x = L / 2 + Math.cos(a) * r; n.y = A / 2 + Math.sin(a) * r * 0.8 })
          for (let i = 0; i < 420; i++) passo()
        }
        desenhar()
        if (!selecionado) detalhar(null)
      },
    }
  }

  // ---------- abas ----------
  function montarAbas(grafo) {
    const barra = $('#abas')
    const secoes = document.querySelectorAll('#conteudo-painel section')
    function abrir(id) {
      secoes.forEach(s => { s.hidden = s.dataset.aba !== id })
      barra.querySelectorAll('button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.aba === id)))
      if (id === 'grafo') grafo.abrir()
    }
    for (const [id, nome] of ABAS) {
      const b = el('button', '', nome)
      b.type = 'button'; b.dataset.aba = id
      b.setAttribute('role', 'tab')
      b.addEventListener('click', () => { history.replaceState(null, '', '#' + id); abrir(id) })
      barra.append(b)
    }
    abrir(ABAS.some(([id]) => '#' + id === location.hash) ? location.hash.slice(1) : 'arquitetura')
  }

  async function iniciar() {
    let me
    try { me = await Api.me() } catch { me = {} }
    if (!me.usuario) { location.replace('chat.html'); return }
    Topo.montar(me.usuario, 'tecnico')
    try {
      const dados = await Api.painel()
      $('#conteudo-painel').innerHTML = dados.html   // texto nosso, gerado no deploy
      desenharBenchmark(dados.benchmark)
      desenharCarga(dados.carga)
      desenharDados(dados.inventario, dados.exemplo)
      montarAbas(criarGrafo(dados.grafo))
      $('#pagina').hidden = false
      const aberta = document.querySelector('#abas [aria-selected="true"]')
      if (aberta) aberta.click()
    } catch (e) {
      const erro = $('#erro-painel')
      erro.textContent = 'Não consegui carregar a área técnica. Tente de novo em instantes.'
      erro.hidden = false
    } finally {
      $('#carregando').hidden = true
    }
  }
  iniciar()
})()
