# Como alimentar a base de conhecimento

A página `demo-chat.html` responde perguntas sobre documentos com base no arquivo `conhecimento.js`.
Você não escreve esse arquivo: ele é gerado a partir dos seus documentos.

## Passo a passo

1. Coloque os documentos na pasta `conhecimento/` (Word, Markdown, texto, PDF ou JSON).
2. Dê dois cliques em `gerar-conhecimento.bat`. Se preferir o terminal:
   `python docs/apresentacao/gerar_conhecimento.py`
3. Atualize a página `demo-chat.html` no navegador.

O comando mostra quantos registros saíram de cada arquivo. Se um arquivo der erro, os outros continuam.

## Formatos

| Formato | Observação |
|---|---|
| `.docx` | Os títulos do Word (estilo "Título 1", "Título 2") separam os registros. |
| `.md` | Cada título com `#` abre um registro. |
| `.txt` | A primeira linha de cada bloco, se for curta e sem ponto final, vira o título do que vem abaixo. Blocos são separados por linha em branco. |
| `.pdf` | Só com `pip install pypdf`. PDF escaneado (imagem) não tem texto para ler. |
| `.json` | Lista de objetos com `titulo` e `texto` (ou `problema` e `solucao`). |

## Linhas opcionais dentro de cada seção

```text
## Título do assunto
Pergunta: pergunta de exemplo que aparece como botão no chat
Palavras-chave: termo1, termo2
Origem: de onde veio a informação (aparece em "Ver fonte")
Problema: o que acontece
Solução: o que fazer
```

Nenhuma é obrigatória. Sem `Origem`, vale o nome do arquivo. Sem títulos, o texto é cortado por parágrafos.

## Limites desta versão

- A busca é por palavras, não por significado. Use no texto os termos que as pessoas vão perguntar.
- A resposta mostra o trecho do documento como está, sem resumir nem reescrever.
- Os documentos viram dados da página e ficam visíveis a quem a abrir. Não coloque nada confidencial.
- Para o artefato publicado no claude.ai, o conteúdo precisa ser incluído de novo na hora de publicar.
