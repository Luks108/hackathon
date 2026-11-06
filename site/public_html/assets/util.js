// Funções pequenas que as páginas internas dividem. Nada daqui usa innerHTML: o texto sempre entra por textContent.
(() => {
  const el = (tag, classe, texto) => {
    const e = document.createElement(tag)
    if (classe) e.className = classe
    if (texto !== undefined) e.textContent = texto
    return e
  }

  // 5587988887777 -> (87) 98888-7777. Devolve o texto original se não for um celular de 13 dígitos.
  const formatarTelefone = n => {
    const m = /^55(\d{2})(9\d{4})(\d{4})$/.exec(String(n))
    return m ? `(${m[1]}) ${m[2]}-${m[3]}` : String(n)
  }

  // "2026-11-06 02:31:07" -> "06/11/2026 02:31". O servidor manda a hora dele, sem fuso.
  const dataHora = s => {
    const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(String(s || ''))
    return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : ''
  }

  const ENTES = { 'pe-garanhuns': 'Município de Garanhuns', 'pe-estado': 'Estado de Pernambuco' }
  const nomesDosEntes = tenants => (tenants || []).map(t => ENTES[t] || t).join(' e ')

  window.U = { el, formatarTelefone, dataHora, nomesDosEntes }
})()
