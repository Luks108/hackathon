// Identidade única por tipo. Vale também como índice das buscas por id.
CREATE CONSTRAINT ente_id IF NOT EXISTS FOR (n:Ente) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT uj_id IF NOT EXISTS FOR (n:UnidadeJurisdicionada) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT processo_id IF NOT EXISTS FOR (n:ProcessoLicitatorio) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT contrato_id IF NOT EXISTS FOR (n:Contrato) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT fornecedor_id IF NOT EXISTS FOR (n:Fornecedor) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT sancao_id IF NOT EXISTS FOR (n:Sancao) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT execucao_id IF NOT EXISTS FOR (n:ExecucaoFinanceira) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT cadastro_receita_id IF NOT EXISTS FOR (n:CadastroReceita) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT evidencia_id IF NOT EXISTS FOR (n:Evidencia) REQUIRE n.id IS UNIQUE;
CREATE INDEX contrato_tenant IF NOT EXISTS FOR (n:Contrato) ON (n.tenant);
CREATE INDEX processo_tenant IF NOT EXISTS FOR (n:ProcessoLicitatorio) ON (n.tenant);
// Índices de texto das buscas (consulta/busca.py monta a consulta). `standard-folding` ignora acento e maiúscula.
// O antigo `fornecedor_nome` era do analisador padrão (acento conta): é recriado, e a carga espera os índices ficarem prontos.
// O nome fantasia entra no índice: a marca (ex.: BERNHOEFT) costuma estar nele, e não na razão social.
DROP INDEX fornecedor_nome IF EXISTS;
CREATE FULLTEXT INDEX fornecedor_nome IF NOT EXISTS FOR (n:Fornecedor) ON EACH [n.nome, n.nome_fantasia] OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-folding'}};
CREATE FULLTEXT INDEX contrato_objeto IF NOT EXISTS FOR (n:Contrato) ON EACH [n.objeto] OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-folding'}};
CREATE FULLTEXT INDEX unidade_nome IF NOT EXISTS FOR (n:UnidadeJurisdicionada) ON EACH [n.nome] OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-folding'}};
