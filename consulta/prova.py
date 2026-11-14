"""Abrir uma evidência e escolher quais evidências sustentam uma resposta. Sem rede e sem modelo: a parte pura.

Dois usos, uma regra só:
  1. `abrir` é a consulta que a tool `conferir_evidencia` do servidor MCP executa. O agente a usa de novo, em tempo de
     execução, para abrir a prova que o modelo deixou de abrir. Quem decide ente e sensibilidade é quem passa `executar`
     (o ambiente do perfil); este arquivo não sabe quem perguntou.
  2. `escolher` liga a resposta aos fatos que as tools devolveram: só vale a evidência de um fato que a resposta de fato
     cita (número do contrato, valor ou data da sanção; o nome só ordena). Resposta que não cita nenhum fato não ganha prova inventada.
"""

import hashlib
import re
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ID_EVIDENCIA = re.compile(r"^[A-Za-z0-9:_\-]{1,80}$")
LIMITE_PROVAS = 3          # quantas evidências uma resposta mostra (é o mesmo teto que a regra 2 do prompt dá ao modelo)
VALOR_MINIMO = 1000        # abaixo disso o número solto é ambíguo demais para provar que a resposta falou daquele fato
CAMPOS_DE_VALOR = ("valor_contratado", "empenhado", "liquidado", "pago", "restos_a_pagar", "valor_multa")
CAMPOS_DE_NOME = ("fornecedor", "unidade", "orgao")
CAMPOS_DE_DATA = ("publicada_em", "fim_suspensao")      # a data da sanção identifica a ocorrência; a de início de contrato se repete demais

CONSULTA = """
    MATCH (e:Evidencia {id: $id}) WHERE e.tenant IN $tenants
    MATCH (fato)-[:PROVADO_POR]->(e)
    WHERE NOT fato:Fornecedor AND fato.sensibilidade IN $sensibilidades
    RETURN e.trecho AS trecho, e.url AS url, e.arquivo AS arquivo, e.documento_hash AS documento_hash,
           e.tabela AS tabela, e.linha AS linha, e.capturado_em AS capturado_em,
           e.trecho_mascarado AS trecho_mascarado
    LIMIT 1"""


def pasta_bruto(variavel: str | None) -> Path:
    """Pasta dos arquivos brutos. Relativa vale a partir da raiz do projeto, nunca do diretório atual."""
    pasta = Path(variavel or "fixtures/exemplo/bruto")
    return pasta if pasta.is_absolute() else RAIZ / pasta


def id_valido(valor: str) -> str:
    valor = (valor or "").strip()
    if not ID_EVIDENCIA.match(valor):
        raise ValueError("evidencia_id inválido: use o id devolvido pelas outras tools")
    return valor


def abrir(executar, evidencia_id: str, bruto: Path) -> dict:
    """Abre a evidência: trecho, endereço da fonte e se o arquivo guardado ainda bate com o hash.
    `executar(cypher, **parametros)` devolve as linhas já filtradas pelo perfil (entes e sensibilidade)."""
    achado = executar(CONSULTA, id=id_valido(evidencia_id))
    if not achado:
        return {"erro": "evidência não encontrada para este perfil"}
    e = achado[0]
    arquivo = bruto / Path(e["arquivo"]).name
    e["hash_confere"] = arquivo.is_file() and hashlib.sha256(arquivo.read_bytes()).hexdigest() == e["documento_hash"]
    return e


# ---------- ligar a resposta aos fatos ----------

def normalizar(texto) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", str(texto)) if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def formas_do_valor(valor) -> list[str]:
    """Jeitos de escrever o valor em português: 1.234.567,89 | 1.234.567 | 3,7 milhões. Valor pequeno não serve de chave."""
    try:
        n = round(float(valor), 2)
    except (TypeError, ValueError):
        return []
    if isinstance(valor, bool) or n < VALOR_MINIMO:
        return []
    troca = str.maketrans({",": ".", ".": ","})
    formas = [f"{n:,.2f}".translate(troca)]
    if n == int(n):
        formas.append(f"{int(n):,}".replace(",", "."))
    if n >= 1_000_000:
        formas += [f"{n / 1e6:.{casas}f}".replace(".", ",") + r"\s*milh" for casas in (2, 1)]
    return formas


def _achar(padrao: str, texto: str) -> int | None:
    achado = re.search(padrao, texto)
    return achado.start() if achado else None


def _posicao_do_numero(numero, texto: str) -> int | None:
    numero = normalizar(numero)
    return _achar(rf"(?<![\d/]){re.escape(numero)}(?![\d/])", texto) if numero else None


def _posicao_do_valor(valor, texto: str) -> int | None:
    posicoes = []
    for forma in formas_do_valor(valor):
        regex = forma if "milh" in forma else re.escape(forma)
        p = _achar(rf"(?<![\d.,]){regex}(?!\d)", texto)
        if p is not None:
            posicoes.append(p)
    return min(posicoes) if posicoes else None


def _nomes_possiveis(nome) -> list[str]:
    inteiro = normalizar(re.sub(r"\(.*?\)", " ", str(nome)))
    sem_sufixo = re.sub(r"\s+(ltda|s/?a|me|epp|eireli)\.?$", "", inteiro).strip()
    return [n for n in dict.fromkeys([inteiro, sem_sufixo]) if len(n) >= 4]


def _posicao_do_nome(nome, texto: str) -> int | None:
    posicoes = [p for n in _nomes_possiveis(nome) if (p := _achar(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", texto)) is not None]
    return min(posicoes) if posicoes else None


def _posicao_da_data(data, texto: str) -> int | None:
    """Data ISO (2025-01-15) escrita como 15/01/2025 ou como veio."""
    achado = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(data or ""))
    if not achado:
        return None
    ano, mes, dia = achado.groups()
    posicoes = [p for forma in (f"{dia}/{mes}/{ano}", f"{ano}-{mes}-{dia}")
                if (p := _achar(rf"(?<![\d/-]){re.escape(forma)}(?![\d/-])", texto)) is not None]
    return min(posicoes) if posicoes else None


def _pontuar(fato: dict, texto: str) -> tuple[int, int] | None:
    """(pontos, posição na resposta) do fato, ou None se a resposta não o cita. Só conta quem a resposta ANCORA em algo específico:
    o número do contrato, um valor ou a data da sanção (3 pontos cada). O nome do fornecedor ou do órgão (1 ponto) só ajuda a ordenar:
    sozinho não liga, porque o mesmo nome aparece em dezenas de contratos que a resposta não citou."""
    pontos, posicoes = 0, []
    achado = _posicao_do_numero(fato.get("numero"), texto)
    if achado is not None:
        pontos, posicoes = pontos + 3, posicoes + [achado]
    valores = [p for c in CAMPOS_DE_VALOR if (p := _posicao_do_valor(fato.get(c), texto)) is not None]
    if valores:
        pontos, posicoes = pontos + 3, posicoes + valores
    datas = [p for c in CAMPOS_DE_DATA if (p := _posicao_da_data(fato.get(c), texto)) is not None]
    if datas:
        pontos, posicoes = pontos + 3, posicoes + datas
    if not pontos:
        return None
    nomes = [p for c in CAMPOS_DE_NOME if (p := _posicao_do_nome(fato.get(c), texto)) is not None]
    if nomes:
        pontos, posicoes = pontos + 1, posicoes + nomes
    return pontos, min(posicoes)


def escolher(fatos: list[dict], resposta: str, abertas, limite: int = LIMITE_PROVAS) -> list[str]:
    """Os ids das evidências que sustentam o que a resposta diz e que ainda não foram abertas, no máximo `limite`.
    Cada fato é um item devolvido por uma tool, com o campo `evidencia`. Entram os que a resposta cita pelo número do
    contrato, por um valor ou pela data da sanção, do mais bem ligado para o menos e, em empate, na ordem em que aparecem no texto."""
    texto = normalizar(resposta)
    melhores: dict[str, tuple[int, int]] = {}
    for fato in fatos:
        ident = fato.get("evidencia")
        if not isinstance(ident, str) or ident in abertas:
            continue
        nota = _pontuar(fato, texto)
        if nota and (ident not in melhores or (-nota[0], nota[1]) < (-melhores[ident][0], melhores[ident][1])):
            melhores[ident] = nota
    ordem = sorted(melhores, key=lambda i: (-melhores[i][0], melhores[i][1]))
    return ordem[:max(0, limite)]


AFIRMACAO = re.compile(r"R\$\s?\d|(?<![\d/])\d{1,4}/\d{4}(?!\d)")


def cita_valor_ou_contrato(resposta: str) -> bool:
    """A resposta traz um valor em reais ou um número de contrato (algo que pede prova)?"""
    return bool(AFIRMACAO.search(resposta or ""))
