// Página "Modelos lado a lado": os modelos do benchmark comparados nas mesmas perguntas.
// Os dados vêm de /api/painel (benchmark.linhas), que exige login. SVG puro, sem biblioteca.
// Todo texto vindo dos dados entra por textContent / setAttribute, nunca como HTML.
(() => {
  'use strict'
  const { el } = window.U
  const $ = s => document.querySelector(s)
  const NS = 'http://www.w3.org/2000/svg'

  // Cor fixa por modelo: a cor segue a entidade, não a posição. Ordem das cores validada (daltonismo) para até 4 séries vizinhas.
  const CORES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300']
  const MODELOS = {
    'claude-opus-5-5': { nome: 'Claude Opus 5.5', provedor: 'Claude', slot: 0 },
    'claude-sonnet-5-5': { nome: 'Claude Sonnet 5.5', provedor: 'Claude', slot: 1 },
    'deepseek:deepseek-flash': { nome: 'DeepSeek Flash', provedor: 'DeepSeek', slot: 2 },
    'deepseek:deepseek-v4-pro': { nome: 'DeepSeek V4 Pro', provedor: 'DeepSeek', slot: 3 },
  }
  const TIPOS = [['fato', 'Fato'], ['limite', 'Limite'], ['isolamento', 'Isolamento'], ['ausencia', 'Ausência'], ['ataque', 'Ataque']]

  const estado = { b: null, ordem: [], ativos: new Set(), tabelas: {} }

  // ---------- números ----------
  const pct = (k, n) => (n ? (100 * k) / n : 0)
  const f1 = n => n.toFixed(1).replace('.', ',')
  const fp = n => `${f1(n)}%`
  const fs = n => `${n.toFixed(1).replace('.', ',')} s`
  const inteiro = n => (n == null ? '—' : Number(n).toLocaleString('pt-BR'))
  const dolar = n => (n == null ? '—' : `US$ ${Number(n).toFixed(n < 1 ? 3 : 2).replace('.', ',')}`)
  const soma = (ls, f) => ls.reduce((n, l) => n + f(l), 0)

  // Intervalo de confiança de Wilson (95%) para uma proporção.
  function wilson(k, n, z = 1.96) {
    if (!n) return [0, 0]
    const p = k / n, d = 1 + (z * z) / n, c = p + (z * z) / (2 * n)
    const m = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))
    return [Math.max(0, (c - m) / d), Math.min(1, (c + m) / d)]
  }
  function quantil(ordenado, q) {
    if (!ordenado.length) return 0
    const pos = (ordenado.length - 1) * q, i = Math.floor(pos), r = pos - i
    return ordenado[i] + (ordenado[Math.min(i + 1, ordenado.length - 1)] - ordenado[i]) * r
  }
  // McNemar exato: b = só A acertou, c = só B acertou. P-valor bicaudal da binomial(b+c, 1/2).
  function mcnemar(b, c) {
    const n = b + c
    if (!n) return 1
    const lf = [0]
    for (let i = 1; i <= n; i++) lf[i] = lf[i - 1] + Math.log(i)
    const pmf = i => Math.exp(lf[n] - lf[i] - lf[n - i] - n * Math.LN2)
    let cauda = 0
    for (let i = 0; i <= Math.min(b, c); i++) cauda += pmf(i)
    return Math.min(1, 2 * cauda)
  }

  // ---------- identidade dos modelos ----------
  function identidade(id, i = 0) {
    const conhecido = MODELOS[id]
    if (conhecido) return { ...conhecido, cor: CORES[conhecido.slot] }
    const info = (estado.b.modelos && estado.b.modelos[id]) || {}
    const prov = info.provedor_nome || (id.includes(':') ? id.split(':')[0] : 'Claude')
    return { nome: `${prov} · ${id.replace(/^[a-z]+:/, '')}`, provedor: prov, slot: 4 + i, cor: CORES[4 + i] || '#898781' }
  }
  const quem = {}   // id -> identidade
  const clara = (hex, t) => {   // mistura com branco: serve para o "certo, mas sem prova"
    const n = parseInt(hex.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255]
    return '#' + c.map(v => Math.round(v + (255 - v) * t).toString(16).padStart(2, '0')).join('')
  }

  // ---------- métricas por modelo ----------
  function metricas(id) {
    const linhas = estado.b.linhas.filter(l => (l.modelo || estado.b.modelo) === id)
    const a = linhas.filter(l => l.braco === 'fornexia')
    const fatos = a.filter(l => l.tipo === 'fato')
    const exigemProva = fatos.filter(l => l.provar !== false)
    const tempos = a.map(l => l.total_s).sort((x, y) => x - y)
    const k = soma(a, l => l.nota)
    const porTipo = {}
    for (const [t] of TIPOS) {
      const g = a.filter(l => l.tipo === t)
      porTipo[t] = { n: g.length, k: soma(g, l => l.nota) }
    }
    const validas = linhas.filter(l => !l.desfecho || l.desfecho === 'ok')   // chamada com erro não tem custo informado
    const custos = validas.map(l => l.custo_usd)
    const comCusto = custos.length > 0 && custos.every(c => c != null)
    return {
      id, a, linhas, n: a.length, k, ic: wilson(k, a.length), porTipo,
      provadas: exigemProva.filter(l => l.certo && l.provada).length,
      semProva: exigemProva.filter(l => l.certo && !l.provada).length,
      erradas: exigemProva.filter(l => !l.certo).length,
      nExigem: exigemProva.length,
      tempos, mediana: quantil(tempos, 0.5), q1: quantil(tempos, 0.25), q3: quantil(tempos, 0.75),
      p10: quantil(tempos, 0.1), p90: quantil(tempos, 0.9), media: tempos.length ? soma(tempos, x => x) / tempos.length : 0,
      tokensIn: linhas.some(l => l.tokens_entrada != null) ? soma(linhas, l => l.tokens_entrada || 0) : null,
      tokensOut: linhas.some(l => l.tokens_saida != null) ? soma(linhas, l => l.tokens_saida || 0) : null,
      custoPor100: comCusto ? (soma(validas, l => l.custo_usd) / validas.length) * 100 : null,
      custoOrigem: (estado.b.modelos && estado.b.modelos[id] && estado.b.modelos[id].custo_origem) || '',
      erros: linhas.filter(l => l.desfecho && l.desfecho !== 'ok').length,
    }
  }
  const ativosOrdenados = () => estado.ordem.filter(id => estado.ativos.has(id))

  // ---------- SVG ----------
  function S(tag, attrs = {}, filhos = []) {
    const e = document.createElementNS(NS, tag)
    for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, String(v))
    for (const f of [].concat(filhos)) if (f != null) e.append(f)
    return e
  }
  const T = (x, y, texto, classe = '', extra = {}) => { const t = S('text', { x, y, class: classe, ...extra }); t.textContent = texto; return t }
  // barra horizontal com a ponta de dados arredondada (4 px) e a base reta, crescendo de x0
  function barraH(x0, y, w, h, cor, r = 4) {
    if (w <= 0) return null
    if (w <= r * 2) return S('rect', { x: x0, y, width: Math.max(w, 1), height: h, fill: cor })
    return S('path', { d: `M${x0},${y} h${w - r} a${r},${r} 0 0 1 ${r},${r} v${h - 2 * r} a${r},${r} 0 0 1 -${r},${r} h-${w - r} z`, fill: cor })
  }
  const larguraDe = el0 => Math.max(300, Math.floor(el0.clientWidth || 640))

  // ---------- dica flutuante ----------
  const dica = () => $('#dica')
  function mostrarDica(alvo, linhas, ev) {
    const d = dica()
    d.replaceChildren()
    linhas.forEach((l, i) => {
      if (i === 0) { d.append(el('b', '', l.texto || l)); return }
      const p = el('div', 'l')
      if (l.cor) { const c = el('span', 'c'); c.style.background = l.cor; p.append(c) }
      p.append(document.createTextNode(l.texto || l))
      d.append(p)
    })
    d.hidden = false
    const r = ev && ev.clientX != null ? { x: ev.clientX, y: ev.clientY } : (() => { const b = alvo.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top } })()
    const w = d.offsetWidth, h = d.offsetHeight
    d.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.x + 14))}px`
    d.style.top = `${Math.max(8, r.y - h - 12 < 8 ? r.y + 18 : r.y - h - 12)}px`
  }
  const esconderDica = () => { dica().hidden = true }
  function comDica(no, linhas, rotuloAria) {
    no.setAttribute('data-dica', '1')
    if (rotuloAria) { no.setAttribute('tabindex', '0'); no.setAttribute('role', 'img'); no.setAttribute('aria-label', rotuloAria) }
    no.addEventListener('pointermove', ev => mostrarDica(no, linhas, ev))
    no.addEventListener('pointerleave', esconderDica)
    no.addEventListener('focus', () => mostrarDica(no, linhas))
    no.addEventListener('blur', esconderDica)
    return no
  }

  // ---------- eixo horizontal ----------
  function eixoX(g, x0, x1, yTopo, yBase, min, max, passo, formato) {
    const esc = v => x0 + ((v - min) / (max - min)) * (x1 - x0)
    for (let v = min; v <= max + 1e-9; v += passo) {
      g.append(S('line', { x1: esc(v), x2: esc(v), y1: yTopo, y2: yBase, class: 'grade' }))
      g.append(T(esc(v), yBase + 16, formato(v), '', { 'text-anchor': 'middle' }))
    }
    g.append(S('line', { x1: x0, x2: x1, y1: yBase, y2: yBase, class: 'eixo' }))
    return esc
  }

  // ---------- tabela gêmea de cada gráfico ----------
  function tabelaDe(cabecalho, linhas) {
    const t = el('table')
    const thead = el('thead'), tr = el('tr')
    cabecalho.forEach(h => tr.append(el('th', '', h)))
    thead.append(tr)
    const tbody = el('tbody')
    linhas.forEach(l => { const r = el('tr'); l.forEach(c => r.append(el('td', c && c.classe ? c.classe : '', c && c.texto !== undefined ? c.texto : c))); tbody.append(r) })
    t.append(thead, tbody)
    return t
  }
  const comNome = id => ({ texto: quem[id].nome, classe: 'nome' })

  // ============================ gráficos ============================
  // 1) Nota total: ponto com intervalo de 95%. O eixo não começa em zero (é ponto, não barra): mostra se os intervalos se sobrepõem.
  function graficoNota(ms) {
    const caixa = $('#c-nota .viz-corpo'), W = larguraDe(caixa), estreito = W < 560
    const L = estreito ? 14 : 150, R = estreito ? 14 : 150, linhaH = estreito ? 62 : 46, topo = 6, base = topo + ms.length * linhaH
    const minimo = Math.min(...ms.map(m => m.ic[0]))
    const min = Math.max(0, Math.floor((minimo * 100 - 4) / 5) * 5), max = 100
    const svg = S('svg', { width: W, height: base + 28, viewBox: `0 0 ${W} ${base + 28}`, role: 'group', 'aria-label': 'Nota total por modelo, com intervalo de 95%' })
    const esc = eixoX(svg, L, W - R, topo, base, min, max, 5, v => `${v}%`)
    ms.slice().sort((x, y) => y.k / (y.n || 1) - x.k / (x.n || 1)).forEach((m, i) => {
      const y = topo + i * linhaH + linhaH / 2, cor = quem[m.id].cor, p = pct(m.k, m.n)
      const yNome = estreito ? y - 16 : y + 4
      svg.append(S('rect', { x: estreito ? 14 : 8, y: yNome - 11, width: 12, height: 12, rx: 3, fill: cor }))
      svg.append(T(estreito ? 32 : 26, yNome, quem[m.id].nome, 'forte'))
      const yy = estreito ? y + 8 : y
      const g = S('g')
      g.append(S('line', { x1: esc(m.ic[0] * 100), x2: esc(m.ic[1] * 100), y1: yy, y2: yy, stroke: cor, 'stroke-width': 2.5, 'stroke-linecap': 'round' }))
      g.append(S('circle', { cx: esc(p), cy: yy, r: 6, fill: cor, stroke: '#fff', 'stroke-width': 2 }))
      svg.append(comDica(g, [quem[m.id].nome, { texto: `${fp(p)} · ${m.k} de ${m.n} perguntas`, cor },
        { texto: `Intervalo de 95%: ${fp(m.ic[0] * 100)} a ${fp(m.ic[1] * 100)}` }], `${quem[m.id].nome}: ${fp(p)}, ${m.k} de ${m.n}`))
      if (estreito) svg.append(T(W - 14, yNome, `${fp(p)} · ${m.k}/${m.n}`, 'valor', { 'text-anchor': 'end' }))
      else svg.append(T(Math.min(W - R + 12, esc(m.ic[1] * 100) + 12), yy + 4, `${fp(p)} · ${m.k}/${m.n}`, 'valor'))
    })
    caixa.replaceChildren(svg)
    estado.tabelas['c-nota'] = tabelaDe(['Modelo', 'Passou', 'Total', 'Nota', 'Intervalo de 95%'], ms.map(m => [comNome(m.id), { texto: String(m.k), classe: 'num' },
      { texto: String(m.n), classe: 'num' }, { texto: fp(pct(m.k, m.n)), classe: 'num' }, { texto: `${fp(m.ic[0] * 100)} a ${fp(m.ic[1] * 100)}`, classe: 'num' }]))
  }

  // 2) Nota por tipo: barras agrupadas (parte de zero)
  function graficoTipo(ms) {
    const caixa = $('#c-tipo .viz-corpo'), W = larguraDe(caixa), estreito = W < 560
    const L = estreito ? 14 : 150, R = 16, esp = 2, bh = 12, grupoH = ms.length * (bh + esp) + 22, topo = 4
    const tipos = TIPOS.filter(([t]) => ms.some(m => m.porTipo[t].n > 0))
    const base = topo + tipos.length * grupoH
    const svg = S('svg', { width: W, height: base + 28, viewBox: `0 0 ${W} ${base + 28}`, role: 'group', 'aria-label': 'Nota por tipo de pergunta' })
    const esc = eixoX(svg, L, W - R, topo, base, 0, 100, 25, v => `${v}%`)
    tipos.forEach(([t, nome], gi) => {
      const y0 = topo + gi * grupoH + 6
      const n = ms[0].porTipo[t].n
      svg.append(T(estreito ? 14 : 8, y0 + (estreito ? 0 : (ms.length * (bh + esp)) / 2 + 4), `${nome} · ${n}`, 'forte', estreito ? { y: y0 - 2 } : {}))
      ms.forEach((m, i) => {
        const d = m.porTipo[t], y = y0 + i * (bh + esp) + (estreito ? 8 : 0), p = pct(d.k, d.n), cor = quem[m.id].cor
        const g = S('g')
        g.append(S('rect', { x: L, y: y - 1, width: W - R - L, height: bh + 2, fill: 'transparent' }))
        const b = barraH(L, y, Math.max(0, esc(p) - L), bh, cor, 4)
        if (b) g.append(b)
        svg.append(comDica(g, [`${quem[m.id].nome} · ${nome}`, { texto: `${fp(p)} · ${d.k} de ${d.n}`, cor }], `${quem[m.id].nome}, ${nome}: ${fp(p)}`))
      })
    })
    caixa.replaceChildren(legenda(ms), svg)
    estado.tabelas['c-tipo'] = tabelaDe(['Tipo', 'Perguntas', ...ms.map(m => quem[m.id].nome)],
      tipos.map(([t, nome]) => [nome, { texto: String(ms[0].porTipo[t].n), classe: 'num' }, ...ms.map(m => ({ texto: `${fp(pct(m.porTipo[t].k, m.porTipo[t].n))} (${m.porTipo[t].k}/${m.porTipo[t].n})`, classe: 'num' }))]))
  }

  // 3) Tempo: faixa interquartil + mediana + linha de p10 a p90
  function graficoTempo(ms) {
    const caixa = $('#c-tempo .viz-corpo'), W = larguraDe(caixa), estreito = W < 560
    const L = estreito ? 14 : 150, R = estreito ? 14 : 170, linhaH = estreito ? 62 : 46, topo = 6, base = topo + ms.length * linhaH
    const maxV = Math.max(...ms.map(m => m.p90)) * 1.08, passo = maxV > 60 ? 20 : maxV > 30 ? 10 : 5
    const max = Math.ceil(maxV / passo) * passo
    const svg = S('svg', { width: W, height: base + 28, viewBox: `0 0 ${W} ${base + 28}`, role: 'group', 'aria-label': 'Tempo por resposta' })
    const esc = eixoX(svg, L, W - R, topo, base, 0, max, passo, v => `${v} s`)
    ms.forEach((m, i) => {
      const y = topo + i * linhaH + linhaH / 2, cor = quem[m.id].cor, yy = estreito ? y + 8 : y, yNome = estreito ? y - 16 : y + 4
      svg.append(S('rect', { x: estreito ? 14 : 8, y: yNome - 11, width: 12, height: 12, rx: 3, fill: cor }))
      svg.append(T(estreito ? 32 : 26, yNome, quem[m.id].nome, 'forte'))
      const g = S('g')
      g.append(S('line', { x1: esc(m.p10), x2: esc(m.p90), y1: yy, y2: yy, stroke: cor, 'stroke-width': 2, 'stroke-linecap': 'round' }))
      g.append(S('rect', { x: esc(m.q1), y: yy - 8, width: Math.max(esc(m.q3) - esc(m.q1), 3), height: 16, rx: 4, fill: cor }))
      g.append(S('rect', { x: esc(m.mediana) - 1.5, y: yy - 8, width: 3, height: 16, fill: '#fff' }))
      svg.append(comDica(g, [quem[m.id].nome, { texto: `Mediana ${fs(m.mediana)} · média ${fs(m.media)}`, cor },
        { texto: `Metade das respostas: ${fs(m.q1)} a ${fs(m.q3)}` }, { texto: `10% mais rápidas até ${fs(m.p10)}; 10% mais lentas a partir de ${fs(m.p90)}` }],
        `${quem[m.id].nome}: mediana ${fs(m.mediana)}`))
      if (estreito) svg.append(T(W - 14, yNome, `mediana ${fs(m.mediana)}`, 'valor', { 'text-anchor': 'end' }))
      else svg.append(T(Math.min(W - R + 12, esc(m.p90) + 12), yy + 4, `mediana ${fs(m.mediana)}`, 'valor'))
    })
    caixa.replaceChildren(svg)
    estado.tabelas['c-tempo'] = tabelaDe(['Modelo', 'Mediana', 'Média', '1º quartil', '3º quartil', '10º percentil', '90º percentil', 'Soma'],
      ms.map(m => [comNome(m.id), ...[m.mediana, m.media, m.q1, m.q3, m.p10, m.p90].map(v => ({ texto: fs(v), classe: 'num' })), { texto: `${Math.round(soma(m.tempos, x => x))} s`, classe: 'num' }]))
  }

  // 4) Evidência: barra 100% por modelo (certa e provada / certa sem prova / errada)
  function graficoProva(ms) {
    const caixa = $('#c-prova .viz-corpo'), W = larguraDe(caixa), estreito = W < 560
    const L = estreito ? 14 : 150, R = estreito ? 14 : 150, linhaH = estreito ? 62 : 46, topo = 6, base = topo + ms.length * linhaH
    const svg = S('svg', { width: W, height: base + 28, viewBox: `0 0 ${W} ${base + 28}`, role: 'group', 'aria-label': 'Fatos com evidência conferida' })
    const esc = eixoX(svg, L, W - R, topo, base, 0, 100, 25, v => `${v}%`)
    ms.forEach((m, i) => {
      const y = topo + i * linhaH + linhaH / 2, cor = quem[m.id].cor, yy = (estreito ? y + 8 : y) - 11, yNome = estreito ? y - 16 : y + 4
      svg.append(S('rect', { x: estreito ? 14 : 8, y: yNome - 11, width: 12, height: 12, rx: 3, fill: cor }))
      svg.append(T(estreito ? 32 : 26, yNome, quem[m.id].nome, 'forte'))
      const partes = [['Certa e com prova conferida', m.provadas, cor], ['Certa, mas sem prova', m.semProva, clara(cor, 0.62)], ['Errada', m.erradas, 'var(--viz-falha)']]
      const total = m.nExigem || 1
      let acumulado = 0
      partes.forEach(([nome, k, fill], j) => {
        if (!k) return
        const x0 = esc((100 * acumulado) / total), x1 = esc((100 * (acumulado + k)) / total)
        acumulado += k
        const g = S('g')
        g.append(S('rect', { x: x0 + (j ? 1 : 0), y: yy, width: Math.max(x1 - x0 - (j ? 1 : 0) - 1, 1), height: 22, rx: j === 0 ? 4 : 2, fill }))
        svg.append(comDica(g, [`${quem[m.id].nome} · ${nome}`, { texto: `${k} de ${m.nExigem} fatos (${fp(pct(k, m.nExigem))})`, cor }], `${quem[m.id].nome}, ${nome}: ${k} de ${m.nExigem}`))
      })
      if (estreito) svg.append(T(W - 14, yNome, `${m.provadas}/${m.nExigem} provados`, 'valor', { 'text-anchor': 'end' }))
      else svg.append(T(W - R + 12, yy + 16, `${m.provadas}/${m.nExigem} provados`, 'valor'))
    })
    caixa.replaceChildren(legendaProva(), svg)
    estado.tabelas['c-prova'] = tabelaDe(['Modelo', 'Fatos que exigem prova', 'Certa e provada', 'Certa, sem prova', 'Errada'],
      ms.map(m => [comNome(m.id), { texto: String(m.nExigem), classe: 'num' }, { texto: `${m.provadas} (${fp(pct(m.provadas, m.nExigem))})`, classe: 'num' },
        { texto: `${m.semProva} (${fp(pct(m.semProva, m.nExigem))})`, classe: 'num' }, { texto: `${m.erradas} (${fp(pct(m.erradas, m.nExigem))})`, classe: 'num' }]))
  }

  // 5) Custo por 100 perguntas: barras ranqueadas, valor na ponta
  function graficoCusto(ms) {
    const caixa = $('#c-custo .viz-corpo'), W = larguraDe(caixa), estreito = W < 560
    const com = ms.filter(m => m.custoPor100 != null).sort((x, y) => y.custoPor100 - x.custoPor100)
    const sem = ms.filter(m => m.custoPor100 == null)
    if (!com.length) { caixa.replaceChildren(el('p', 'apoio', 'Nenhum modelo com custo informado ou preço configurado.')); estado.tabelas['c-custo'] = tabelaDe(['Modelo', 'Custo'], ms.map(m => [comNome(m.id), '—'])); return }
    const L = estreito ? 14 : 150, R = estreito ? 90 : 110, linhaH = estreito ? 58 : 40, topo = 6, base = topo + com.length * linhaH
    const maxV = Math.max(...com.map(m => m.custoPor100)), svg = S('svg', { width: W, height: base + 8, viewBox: `0 0 ${W} ${base + 8}`, role: 'group', 'aria-label': 'Custo por 100 perguntas' })
    const x1 = W - R, esc = v => L + (v / maxV) * (x1 - L)
    svg.append(S('line', { x1: L, x2: L, y1: topo, y2: base, class: 'eixo' }))
    com.forEach((m, i) => {
      const y = topo + i * linhaH + linhaH / 2, cor = quem[m.id].cor, yy = estreito ? y + 8 : y, yNome = estreito ? y - 14 : y + 4
      svg.append(S('rect', { x: estreito ? 14 : 8, y: yNome - 11, width: 12, height: 12, rx: 3, fill: cor }))
      svg.append(T(estreito ? 32 : 26, yNome, quem[m.id].nome, 'forte'))
      const g = S('g')
      const b = barraH(L, yy - 10, Math.max(esc(m.custoPor100) - L, 3), 20, cor, 4)
      g.append(S('rect', { x: L, y: yy - 12, width: x1 - L, height: 24, fill: 'transparent' }), b)
      svg.append(comDica(g, [quem[m.id].nome, { texto: `${dolar(m.custoPor100)} a cada 100 perguntas`, cor }, { texto: m.custoOrigem || 'custo' }],
        `${quem[m.id].nome}: ${dolar(m.custoPor100)} por 100 perguntas`))
      svg.append(T(esc(m.custoPor100) + 10, yy + 4, dolar(m.custoPor100), 'valor'))
    })
    caixa.replaceChildren(svg)
    $('#s-custo').textContent = 'Total gasto na rodada dividido pelas chamadas feitas, por 100. O custo do Claude é o que o próprio claude informa; o dos demais é estimado pela tabela de preços (dólar, teto do horário de pico).' +
      (sem.length ? ` Sem preço configurado: ${sem.map(m => quem[m.id].nome).join(', ')}.` : '')
    estado.tabelas['c-custo'] = tabelaDe(['Modelo', 'Custo por 100 perguntas', 'Tokens de entrada', 'Tokens de saída', 'Origem do custo'],
      ms.map(m => [comNome(m.id), { texto: dolar(m.custoPor100), classe: 'num' }, { texto: inteiro(m.tokensIn), classe: 'num' }, { texto: inteiro(m.tokensOut), classe: 'num' }, m.custoOrigem || '—']))
  }

  // 6) Grade pergunta a pergunta
  function perguntasDaGrade(ms) {
    const ordem = Object.fromEntries(TIPOS.map(([t], i) => [t, i]))
    const mapa = new Map()
    for (const m of ms) for (const l of m.a) if (!mapa.has(l.id)) mapa.set(l.id, { id: l.id, tipo: l.tipo, pergunta: l.pergunta })
    return [...mapa.values()].sort((x, y) => (ordem[x.tipo] ?? 9) - (ordem[y.tipo] ?? 9) || x.id.localeCompare(y.id, 'pt', { numeric: true }))
  }
  function graficoGrade(ms) {
    const caixa = $('#c-grade .viz-corpo'), perguntas = perguntasDaGrade(ms), n = perguntas.length
    const L = 150, gap = 10, tipos = [...new Set(perguntas.map(p => p.tipo))], areaMin = 5 * n + gap * (tipos.length - 1)
    const larg = Math.max(areaMin + L + 16, larguraDe(caixa)), cw = (larg - L - 16 - gap * (tipos.length - 1)) / n
    const linhaH = 30, topo = 44, h = topo + ms.length * linhaH + 4
    const svg = S('svg', { width: larg, height: h, viewBox: `0 0 ${larg} ${h}`, role: 'group', 'aria-label': 'Resultado de cada pergunta, por modelo' })
    const porPergunta = new Map(ms.map(m => [m.id, new Map(m.a.map(l => [l.id, l]))]))
    let x = L, ultimoTipo = null, inicioGrupo = L
    const nomeTipo = Object.fromEntries(TIPOS)
    let andar = 0   // rótulos de grupos estreitos alternam de altura para não se sobrepor
    const fechar = xFim => {
      if (!ultimoTipo) return
      const texto = `${nomeTipo[ultimoTipo] || ultimoTipo} · ${perguntas.filter(p => p.tipo === ultimoTipo).length}`
      const estreitoGrupo = xFim - inicioGrupo < texto.length * 7.2
      const linhaDoRotulo = estreitoGrupo ? andar++ % 3 : 0
      svg.append(T(inicioGrupo, estreitoGrupo ? 12 + 13 * linhaDoRotulo : 18, texto, 'forte'))
      if (estreitoGrupo) svg.append(S('line', { x1: inicioGrupo, x2: inicioGrupo, y1: 16 + 13 * linhaDoRotulo, y2: topo - 4, class: 'eixo' }))
    }
    perguntas.forEach(p => {
      if (p.tipo !== ultimoTipo) { if (ultimoTipo) { fechar(x); x += gap } ultimoTipo = p.tipo; inicioGrupo = x }
      ms.forEach((m, i) => {
        const l = porPergunta.get(m.id).get(p.id), cor = quem[m.id].cor, y = topo + i * linhaH
        const passou = l && l.nota === 1, altura = passou ? 20 : 8
        const g = S('g')
        g.append(S('rect', { x, y, width: cw + 1, height: linhaH, fill: 'transparent' }))
        g.append(S('rect', { x: x + 0.5, y: y + (24 - altura) + 3, width: Math.max(cw - 1, 2), height: altura, rx: 1.5, fill: l ? (passou ? cor : 'var(--viz-falha)') : 'none' }))
        svg.append(comDica(g, [`${p.id} · ${nomeTipo[p.tipo] || p.tipo}`, { texto: p.pergunta }, { texto: `${quem[m.id].nome}: ${l ? (passou ? 'passou' : 'não passou') : 'sem resultado'}${l ? ` · ${fs(l.total_s)}` : ''}`, cor }]))
      })
      x += cw
    })
    fechar(x)
    ms.forEach((m, i) => {
      const y = topo + i * linhaH
      svg.append(S('rect', { x: 8, y: y + 8, width: 12, height: 12, rx: 3, fill: quem[m.id].cor }))
      svg.append(T(26, y + 19, quem[m.id].nome, 'forte'))
    })
    caixa.replaceChildren(svg)
  }

  // 7) Onde divergem
  function tabelaDivergencias(ms) {
    const caixa = $('#c-diverge .viz-corpo'), perguntas = perguntasDaGrade(ms)
    const por = new Map(ms.map(m => [m.id, new Map(m.a.map(l => [l.id, l]))]))
    const div = perguntas.filter(p => { const v = ms.map(m => (por.get(m.id).get(p.id) || {}).nota); return new Set(v).size > 1 })
    $('#s-diverge').textContent = div.length
      ? `${div.length} de ${perguntas.length} perguntas tiveram resultado diferente entre os modelos exibidos. Nas outras ${perguntas.length - div.length}, todos passaram ou todos não passaram.`
      : `Os modelos exibidos tiveram o mesmo resultado nas ${perguntas.length} perguntas.`
    if (!div.length) { caixa.replaceChildren(); return }
    const t = el('table'), thead = el('thead'), tr = el('tr')
    ;['Pergunta', ...ms.map(m => quem[m.id].nome)].forEach(h => tr.append(el('th', '', h)))
    thead.append(tr)
    const tbody = el('tbody')
    div.forEach(p => {
      const r = el('tr'), c = el('td', 'pergunta')
      c.append(el('strong', '', `${p.id} `), document.createTextNode(p.pergunta))
      const det = el('details'), sum = el('summary', '', 'Ver as respostas')
      det.append(sum)
      ms.forEach(m => { const l = por.get(m.id).get(p.id); if (l) det.append(el('p', '', `${quem[m.id].nome}: ${l.resposta || '(sem resposta)'}`)) })
      c.append(det)
      r.append(c)
      ms.forEach(m => {
        const l = por.get(m.id).get(p.id), ok = l && l.nota === 1
        r.append(el('td', ok ? 'marca-ok' : 'marca-nao', l ? (ok ? '✓ passou' : '✕ não passou') : '—'))
      })
      tbody.append(r)
    })
    t.append(thead, tbody)
    caixa.replaceChildren(t)
  }

  // 8) Par a par
  function tabelaPares(ms) {
    const caixa = $('#c-par .viz-corpo')
    if (ms.length < 2) { caixa.replaceChildren(el('p', 'apoio', 'Escolha ao menos dois modelos para comparar.')); return { sig: 0, total: 0 } }
    const por = new Map(ms.map(m => [m.id, new Map(m.a.map(l => [l.id, l.nota]))]))
    const linhas = []
    let sig = 0
    for (let i = 0; i < ms.length; i++) for (let j = i + 1; j < ms.length; j++) {
      const A = ms[i], B = ms[j]
      let so1 = 0, so2 = 0, ambos = 0, nenhum = 0
      for (const [id, nota] of por.get(A.id)) {
        if (!por.get(B.id).has(id)) continue
        const o = por.get(B.id).get(id)
        if (nota && o) ambos++; else if (!nota && !o) nenhum++; else if (nota) so1++; else so2++
      }
      const p = mcnemar(so1, so2), real = p < 0.05 && so1 !== so2
      sig += real
      const veredito = so1 === so2 ? 'Empate nas perguntas em que divergem' : real ? `${quem[so1 > so2 ? A.id : B.id].nome} é melhor (p < 0,05)` : 'Diferença pequena demais para separar de sorte'
      linhas.push([{ texto: `${quem[A.id].nome} × ${quem[B.id].nome}`, classe: 'nome' }, { texto: String(so1), classe: 'num' }, { texto: String(so2), classe: 'num' },
        { texto: String(ambos), classe: 'num' }, { texto: p < 0.001 ? '< 0,001' : p.toFixed(3).replace('.', ','), classe: 'num' }, veredito])
    }
    caixa.replaceChildren(tabelaDe(['Par', 'Só o 1º acertou', 'Só o 2º acertou', 'Os dois acertaram', 'p-valor', 'Leitura'], linhas))
    return { sig, total: linhas.length }
  }

  // ---------- peças comuns ----------
  function legenda(ms) {
    const d = el('div', 'viz-legenda')
    ms.forEach(m => { const s = el('span'), i = el('i'); i.style.background = quem[m.id].cor; s.append(i, document.createTextNode(quem[m.id].nome)); d.append(s) })
    return d
  }
  function legendaProva() {
    const d = el('div', 'viz-legenda')
    ;[['#4b5b70', 'Cor cheia: certa e com prova conferida'], ['#b7bcc6', 'Cor clara: certa, mas sem prova'], ['#cfcec6', 'Cinza: errada']].forEach(([cor, texto]) => {
      const s = el('span'), i = el('i'); i.style.background = cor; s.append(i, document.createTextNode(texto)); d.append(s)
    })
    return d
  }
  function cartoes(ms) {
    const raiz = $('#cartoes')
    raiz.replaceChildren(...ms.map(m => {
      const c = el('article', 'viz-modelo'), h = el('h3'), chave = el('span', 'viz-chave')
      chave.style.background = quem[m.id].cor
      h.append(chave, document.createTextNode(quem[m.id].nome))
      const heroi = el('div', 'heroi', fp(pct(m.k, m.n)))
      heroi.append(el('small', '', `${m.k}/${m.n} passaram`))
      const dl = el('dl')
      const linha = (rot, val) => { dl.append(el('dt', '', rot), el('dd', '', val)) }
      linha('Fatos com prova', `${m.provadas}/${m.nExigem}`)
      linha('Tempo mediano', fs(m.mediana))
      linha('Custo por 100 perguntas', dolar(m.custoPor100))
      if (m.erros) linha('Chamadas com erro', String(m.erros))
      c.append(h, el('p', 'prov', quem[m.id].provedor), heroi, dl)
      return c
    }))
  }

  // ---------- orquestração ----------
  function resumoTexto(ms, pares) {
    if (ms.length < 2) return 'Escolha ao menos dois modelos para comparar.'
    const ord = ms.slice().sort((a, b) => b.k / b.n - a.k / a.n), a = ord[0], z = ord[ord.length - 1]
    const dif = a.k - z.k
    const sobrepoe = a.ic[0] <= z.ic[1]
    const tempo = ms.slice().sort((x, y) => x.mediana - y.mediana)
    let t = `Na nota, ${quem[a.id].nome} lidera com ${fp(pct(a.k, a.n))} e ${quem[z.id].nome} fecha com ${fp(pct(z.k, z.n))}: ${dif} pergunta${dif === 1 ? '' : 's'} de diferença em ${a.n}. `
    t += sobrepoe ? 'Os intervalos de 95% se sobrepõem, então a nota sozinha não separa os modelos. ' : 'Os intervalos de 95% não se sobrepõem: a diferença na nota é real. '
    t += `No tempo, ${quem[tempo[0].id].nome} é o mais rápido (mediana ${fs(tempo[0].mediana)}) e ${quem[tempo[tempo.length - 1].id].nome} o mais lento (${fs(tempo[tempo.length - 1].mediana)}). `
    if (pares.total) t += `Par a par, ${pares.sig} de ${pares.total} comparações mostram diferença que não é sorte.`
    return t
  }

  function desenhar() {
    esconderDica()
    const ms = ativosOrdenados().map(metricas)
    if (!ms.length) return
    const b = estado.b
    $('#subtitulo').textContent = `As mesmas ${Math.max(...ms.map(m => m.n))} perguntas, o mesmo gabarito (${b.gabarito}) e as mesmas consultas, trocando só o modelo. Rodada de ${(b.em || '').slice(8, 10)}/${(b.em || '').slice(5, 7)}/${(b.em || '').slice(0, 4)}.`
    cartoes(ms)
    graficoNota(ms)
    graficoTipo(ms)
    graficoTempo(ms)
    graficoProva(ms)
    graficoCusto(ms)
    graficoGrade(ms)
    tabelaDivergencias(ms)
    const pares = tabelaPares(ms)
    $('#resumo').textContent = resumoTexto(ms, pares)
    const nExigem = Math.max(...ms.map(m => m.nExigem))
    $('#s-nota').textContent = `Ponto: percentual de perguntas que passaram. Linha: intervalo de confiança de 95%. Se dois intervalos se sobrepõem, a diferença pode ser acaso. O eixo não começa em zero.`
    $('#s-prova').textContent = `Só os ${nExigem} fatos em que o gabarito exige prova. Uma resposta certa sem a evidência conferida pela base não conta como nota.`
    // mantém as tabelas gêmeas atualizadas dentro dos cartões que estão no modo tabela
    document.querySelectorAll('.viz-card').forEach(card => {
      const t = card.querySelector('.viz-tabela')
      if (t && estado.tabelas[card.id]) t.replaceChildren(estado.tabelas[card.id])
    })
    $('#rodape').textContent = 'Os resultados vêm de uma base inventada para teste e de uma única rodada: dá para comparar os modelos entre si, mas não para prometer esse desempenho em dados reais.'
  }

  function montarFiltro() {
    const caixa = $('#filtro')
    caixa.replaceChildren(...estado.ordem.map(id => {
      const b = el('button'), chave = el('span', 'viz-chave')
      b.type = 'button'
      chave.style.background = quem[id].cor
      b.append(chave, document.createTextNode(quem[id].nome))
      b.setAttribute('aria-pressed', String(estado.ativos.has(id)))
      b.addEventListener('click', () => {
        if (estado.ativos.has(id)) { if (estado.ativos.size > 1) estado.ativos.delete(id) } else estado.ativos.add(id)
        caixa.querySelectorAll('button').forEach((x, i) => x.setAttribute('aria-pressed', String(estado.ativos.has(estado.ordem[i]))))
        desenhar()
      })
      return b
    }))
  }

  function ligarAlternadores() {
    document.querySelectorAll('.viz-alterna').forEach(botao => {
      botao.addEventListener('click', () => {
        const card = botao.closest('.viz-card'), tabela = card.querySelector('.viz-tabela'), corpo = card.querySelector('.viz-corpo')
        const ver = botao.getAttribute('aria-pressed') !== 'true'
        botao.setAttribute('aria-pressed', String(ver))
        botao.textContent = ver ? 'Ver como gráfico' : 'Ver como tabela'
        tabela.hidden = !ver
        corpo.hidden = ver
        if (ver && estado.tabelas[card.id]) tabela.replaceChildren(estado.tabelas[card.id])
      })
    })
  }

  async function iniciar() {
    let me
    try { me = await Api.me() } catch { me = {} }
    if (!me.usuario) { location.replace('chat.html'); return }
    Topo.montar(me.usuario, 'modelos')
    try {
      const dados = await Api.painel()
      const b = dados.benchmark
      if (!b || !Array.isArray(b.linhas) || !b.linhas.length) throw new Error('sem benchmark')
      estado.b = b
      const ids = [...new Set(b.linhas.map(l => l.modelo || b.modelo))]
      let extra = 0
      ids.sort((x, y) => (MODELOS[x] ? MODELOS[x].slot : 9) - (MODELOS[y] ? MODELOS[y].slot : 9))
      ids.forEach(id => { quem[id] = identidade(id, MODELOS[id] ? 0 : extra++) })
      estado.ordem = ids
      estado.ativos = new Set(ids)
      $('#pagina').hidden = false
      montarFiltro()
      ligarAlternadores()
      desenhar()
      let espera = 0
      window.addEventListener('resize', () => { clearTimeout(espera); espera = setTimeout(desenhar, 150) })
    } catch (e) {
      const erro = $('#erro-painel')
      erro.textContent = 'Não consegui carregar os resultados dos modelos. Tente de novo em instantes.'
      erro.hidden = false
    } finally {
      $('#carregando').hidden = true
    }
  }
  iniciar()
})()
