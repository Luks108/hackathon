// Cliente da API. Cuida do cookie de sessão e do token CSRF, e devolve erros com mensagem legível.
(() => {
  let csrf = null

  async function enviar(metodo, caminho, corpo, jaTentou = false) {
    const cab = { Accept: 'application/json' }
    if (corpo !== undefined) cab['Content-Type'] = 'application/json'
    if (metodo !== 'GET') {
      if (!csrf) await me()
      cab['X-CSRF-Token'] = csrf
    }
    let r
    try {
      r = await fetch('/api' + caminho, {
        method: metodo, headers: cab, credentials: 'same-origin',
        body: corpo === undefined ? undefined : JSON.stringify(corpo),
      })
    } catch {
      throw Object.assign(new Error('Não consegui falar com o serviço. Confira sua conexão e tente de novo.'), { status: 0 })
    }
    let dados = null
    if (r.status !== 204) { try { dados = await r.json() } catch { /* corpo vazio ou não JSON */ } }
    if (dados && typeof dados === 'object' && dados.csrf) csrf = dados.csrf
    // Token vencido (sessão renovada em outra aba): busca um novo e repete uma vez.
    if (r.status === 403 && metodo !== 'GET' && !jaTentou) {
      csrf = null
      await me()
      return enviar(metodo, caminho, corpo, true)
    }
    if (!r.ok) {
      throw Object.assign(new Error((dados && dados.erro) || 'Algo deu errado. Tente de novo.'), { status: r.status, dados })
    }
    return dados
  }

  async function me() {
    const dados = await enviar('GET', '/me')
    return dados
  }

  window.Api = {
    me,
    planos: () => enviar('GET', '/planos'),
    painel: () => enviar('GET', '/painel'),
    cadastrar: (nome, email, senha) => enviar('POST', '/cadastro', { nome, email, senha }),
    entrar: (email, senha) => enviar('POST', '/login', { email, senha }),
    sair: () => enviar('POST', '/logout', {}),
    ativarPlano: planoId => enviar('POST', '/assinatura', { plano_id: planoId }),
    perguntar: texto => enviar('POST', '/perguntas', { texto }),
    perguntaAberta: () => enviar('GET', '/perguntas/aberta'),
    eventos: (id, desde) => enviar('GET', `/perguntas/${id}/eventos?desde=${desde}`),
    telefones: () => enviar('GET', '/telefones'),
    cadastrarTelefone: numero => enviar('POST', '/telefones', { numero }),
    removerTelefone: id => enviar('DELETE', `/telefones/${id}`),
    adminTelefones: status => enviar('GET', `/admin/telefones?status=${encodeURIComponent(status)}`),
    aprovarTelefone: id => enviar('POST', `/admin/telefones/${id}/aprovar`, {}),
    revogarTelefone: id => enviar('POST', `/admin/telefones/${id}/revogar`, {}),
    // Demonstração livre: sem escolha de plano, a conta recebe o que cobre mais entes. Devolve o plano, ou null se falhar.
    async garantirPlano() {
      try {
        const planos = await enviar('GET', '/planos')
        const padrao = planos.slice().sort((a, b) => b.tenants.length - a.tenants.length || b.preco_mensal - a.preco_mensal)[0]
        if (!padrao) return null
        return (await enviar('POST', '/assinatura', { plano_id: padrao.id })).plano
      } catch {
        return null
      }
    },
  }
})()
