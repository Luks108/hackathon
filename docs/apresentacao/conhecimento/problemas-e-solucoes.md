# Problemas e soluções do levantamento de fornecedores

## Mesma empresa com grafias diferentes
Pergunta: Como evitar misturar empresas com nomes parecidos?
Palavras-chave: identidade, cnpj, nome
Origem: Captura do portal de Garanhuns
**Problema:** O nome do fornecedor aparece com grafias diferentes nos portais. Juntar pelo nome mistura ou separa empresas.
**Solução:** Usar o CNPJ completo como identidade. O nome serve só para exibição.

## Documento mascarado nos contratos
Pergunta: O que fazer quando o documento do fornecedor vem mascarado?
Palavras-chave: documento, mascara, cnpj, identidade
Origem: Captura do portal de Garanhuns
**Problema:** O portal de contratos mostra o CPF ou CNPJ com asteriscos, o que impede ligar o contrato ao cadastro de sanções.
**Solução:** Recuperar o documento completo em outra tela do portal e aceitar só se a máscara conferir. Sem confirmação, marcar a identidade como não resolvida.

## Valores estimado, adjudicado e contratado
Pergunta: Posso somar o valor estimado com o contratado?
Palavras-chave: valor, licitacao, contrato
Origem: Captura do portal de Garanhuns
**Problema:** Os três valores divergem para a mesma contratação. Somá-los gera um total que não existe.
**Solução:** Guardar cada valor em um campo próprio e nunca somar nem trocar um pelo outro na resposta.

## Pagamentos ainda não ligados a contratos
Pergunta: Por que a resposta não traz o que foi pago ao fornecedor?
Palavras-chave: pagamento, empenho, lacuna
Origem: Backlog do projeto
**Problema:** Os pagamentos não foram coletados, e ainda não se sabe se dá para ligá-los ao contrato.
**Solução:** Declarar na resposta que pagamentos não foram coletados e confirmar a regra de ligação antes de incluí-los.

## Fiscal de contrato com CPF publicado
Pergunta: Como tratar o CPF dos fiscais publicado no portal?
Palavras-chave: lgpd, cpf, pessoa fisica, privacidade
Origem: Captura do portal de Garanhuns
**Problema:** A lista de fiscais publica o CPF completo, que é dado pessoal.
**Solução:** Guardar pessoa física só como código irreversível (HMAC) e retirar o nome do trecho da evidência.

## Sanção em aberto não é prova de irregularidade
Pergunta: Uma sanção em aberto prova que a empresa é irregular?
Palavras-chave: sancao, compliance, irregularidade
Origem: Regras do assistente
**Problema:** Analistas podem ler uma sanção em aberto como condenação definitiva.
**Solução:** Relatar o que a fonte diz, com a data do cadastro, sem julgar. A decisão é do analista.

## Resposta de IA sem fonte
Pergunta: Como garantir que a IA não invente números?
Palavras-chave: evidencia, prova, compliance, ia
Origem: Regras do assistente
**Problema:** Um resumo da IA sem fonte não pode ser conferido e não serve para compliance.
**Solução:** Aceitar na resposta só fatos com evidência: linha, trecho, data da captura e hash do arquivo.

## Analista perde tempo juntando telas
Pergunta: Como reduzir o tempo de levantamento de um fornecedor?
Palavras-chave: tempo, analista, grafo, hipotese
Origem: Entrevista com especialistas (pendente)
**Problema:** Contrato, licitação e sanção ficam em telas diferentes. O levantamento de um fornecedor leva mais de 30 minutos, o que é uma hipótese a validar.
**Solução:** Consultar o grafo por CNPJ e devolver contratos, processo e sanções na mesma resposta, cada um com a sua fonte.
