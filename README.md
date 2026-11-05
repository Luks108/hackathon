# Histórico de fornecedor com prova

Projeto do **Desafio 1 — Portal Inteligente de Transparência com IA** do Hack Garanhuns Tech 2026.

Consulta em linguagem natural a dados públicos de contratação. Toda resposta aponta para o trecho literal
da fonte, e cada perfil vê só o que está autorizado a ver.

> **Estado:** planejamento (Checkpoint 1, 05/11/2026). Este repositório ainda não tem código executável.
> As instruções de execução entram aqui junto com o MVP.

## Problema

O analista de risco de fornecedores precisa identificar a empresa, juntar informações de telas separadas e
provar de onde tirou cada número. Uma resposta de IA sem fonte não serve para compliance.

**Hipótese, ainda não validada:** o levantamento leva mais de 30 minutos por fornecedor e pode cair para
minutos, com fonte conferível. Saberemos que é verdade se 3 especialistas confirmarem.

## Escopo do MVP

**Obrigatório**
- Captura de portal com hash e proveniência
- Normalização de contrato, licitação e fornecedor
- Dois tenants e dois perfis de acesso
- Pergunta em linguagem natural e resposta com âncora conferível
- Registro de consultas e fontes

**Diferenciais**
- Bloqueio entre perfis demonstrado ao vivo
- Três ataques de prompt barrados
- Pessoa física guardada só por hash
- IA declara o que não foi coletado

**Fora do MVP:** vários estados, score de risco, leitura dos PDFs anexos e integração com produtos da Bernhoeft.

## Arquitetura

```text
Portais → Captura → Postgres → Primitivas → Agente
          bruto      fatos      consultas    escolhe a primitiva
          com hash   com        fixas, com   e cita a âncora
                     âncora     filtro por
                                perfil
```

- **Prova:** fato sem âncora não entra no modelo. A resposta abre o trecho literal.
- **Acesso:** o filtro roda antes da LLM. Dado não autorizado nunca chega a ela.
- **Segurança:** o agente não escreve SQL, e o texto do portal é tratado como dado, nunca como instrução.

## Ontologia v1

`Ente` → `UnidadeJurisdicionada`, `ProcessoLicitatorio` → `Participacao`, `Contrato` → `Aditivo`,
`Fornecedor` (PJ ou PF) e `Obra` → `Medicao`. `Despesa` ainda depende de confirmar a ligação entre
pagamento e contrato.

Regras tiradas da captura real:

| Achado | Regra |
|---|---|
| Número de contrato se repete | Identidade pelo id interno do portal |
| Documento vem mascarado | Ligar pelo CNPJ completo |
| Mesma empresa com grafias diferentes | Nome não é identidade |
| Estimado, adjudicado e contratado divergem | Campos distintos, sem somar |
| Lista de fiscais publica CPF completo | Pessoa física guardada só por hash |

## Premissas, limitações e riscos

- O desafio pede portal **estadual**. Até agora capturamos o municipal de Garanhuns; o portal de PE ainda será avaliado.
- A captura cobre contratos, licitações, diárias, obras e legislação. Pagamentos a fornecedores ainda não foram coletados.
- Dado público não é automaticamente livre de LGPD. Dados brutos não são versionados.
- A coleta respeita `robots.txt`, não forja identidade e não contorna bloqueios.
- A tese de valor segue como hipótese até a validação com especialistas.

## Documentos

- [Backlog](docs/BACKLOG.md)
- [Apresentação do Checkpoint 1](docs/apresentacao/checkpoint-1.html): baixe o arquivo e abra no navegador.
