// Identidade única por tipo. Vale também como índice das buscas por id.
CREATE CONSTRAINT ente_id IF NOT EXISTS FOR (n:Ente) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT uj_id IF NOT EXISTS FOR (n:UnidadeJurisdicionada) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT processo_id IF NOT EXISTS FOR (n:ProcessoLicitatorio) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT contrato_id IF NOT EXISTS FOR (n:Contrato) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT fornecedor_id IF NOT EXISTS FOR (n:Fornecedor) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT sancao_id IF NOT EXISTS FOR (n:Sancao) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT evidencia_id IF NOT EXISTS FOR (n:Evidencia) REQUIRE n.id IS UNIQUE;
CREATE INDEX contrato_tenant IF NOT EXISTS FOR (n:Contrato) ON (n.tenant);
CREATE INDEX processo_tenant IF NOT EXISTS FOR (n:ProcessoLicitatorio) ON (n.tenant);
CREATE FULLTEXT INDEX fornecedor_nome IF NOT EXISTS FOR (n:Fornecedor) ON EACH [n.nome];
