// Topo comum das páginas internas (conta e administração): marca, links, nome do usuário e Sair.
// O link da administração só aparece para quem tem o papel admin. O servidor confere o papel de novo a cada requisição.
(() => {
  const { el } = window.U

  function montar(usuario, atual) {
    const topo = document.getElementById('topo')
    topo.replaceChildren()
    const miolo = el('div', 'miolo')

    const marca = el('a', 'marca', 'Fornex')
    marca.href = '/'
    marca.append(el('span', '', 'IA'))

    const links = el('nav', 'topo-links')
    links.setAttribute('aria-label', 'Páginas')
    const itens = [['chat.html', 'Assistente', 'chat'], ['conta.html', 'Minha conta', 'conta']]
    if (usuario.papel === 'admin') itens.push(['admin.html', 'Administração', 'admin'])
    for (const [href, texto, id] of itens) {
      const a = el('a', '', texto)
      a.href = href
      if (id === atual) a.setAttribute('aria-current', 'page')
      links.append(a)
    }

    const direita = el('div', 'topo-acoes')
    direita.append(el('span', 'quem', usuario.nome))
    const sair = el('button', 'link-botao', 'Sair')
    sair.type = 'button'
    sair.addEventListener('click', async () => {
      try { await Api.sair() } catch { /* sai mesmo assim */ }
      location.href = 'chat.html'
    })
    direita.append(sair)

    miolo.append(marca, links, direita)
    topo.append(miolo)
  }

  window.Topo = { montar }
})()
