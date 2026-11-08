"""Gera uma base FICTÍCIA maior (120 contratos), para rodar o benchmark sem a captura real.

    python fixtures/gerar_benchmark.py
    python coleta/carregar_neo4j.py --zerar --benchmark     # carrega no Neo4j (apaga o que houver)
    python bench/benchmark.py gabarito                      # congela as respostas a partir do grafo
    python bench/benchmark.py rodar --modelos claude-opus-5-5,claude-sonnet-5-5
    python coleta/carregar_neo4j.py --zerar --exemplo       # volta à base pequena dos testes de unidade

Tudo é inventado: nomes, CNPJs (sem dígito verificador válido), valores e datas. O mesmo formato da captura real, então
o gabarito, o agente e o painel funcionam sem mudança. A semente é fixa: rodar de novo gera exatamente os mesmos arquivos.

Dimensões pensadas para o gabarito do benchmark (50 perguntas): 84 contratos do Estado em 12 órgãos, 36 de Garanhuns
em 3 unidades, 8 fornecedores nos dois entes, 18 fornecedores sancionados e 26 com execução financeira.
O arquivo bruto vai para fixtures/exemplo/bruto/benchmark.html, ao lado do exemplo.html, para o BRUTO do .env servir aos dois.
"""

import hashlib
import json
import random
from html import escape
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PASTA = RAIZ / "benchmark"
BRUTO = RAIZ / "exemplo" / "bruto"
ARQUIVO = "benchmark.html"
URL = "https://exemplo.invalid/fonte-benchmark"
CAPTURA = "2026-11-05"

# 44 primeiras palavras diferentes entre si: o gabarito reconhece a empresa por ela.
PALAVRAS = [
    "Aurora", "Bromélia", "Cacau", "Dália", "Estrela", "Fogaça", "Girassol", "Horizonte", "Ipê", "Jasmim", "Karité",
    "Lírio", "Mangue", "Nogueira", "Orquídea", "Pitanga", "Quaresma", "Roseira", "Sabiá", "Tamarindo", "Umbu",
    "Vitória-régia", "Xaxim", "Zênite", "Araçá", "Buriti", "Caju", "Dendê", "Embaúba", "Flamboyant", "Guaraná",
    "Hortelã", "Imbuia", "Jacarandá", "Kiwano", "Louro", "Maracujá", "Naja-verde", "Oiti", "Palmeira", "Quixaba",
    "Resedá", "Sapucaia", "Tucumã",
]
RAMOS = [
    ("Engenharia", "obras civis"), ("Serviços Gerais", "serviços gerais"), ("Alimentos", "fornecimento de alimentos"),
    ("Tecnologia", "licenças de software"), ("Transportes", "locação de veículos"), ("Saúde", "insumos hospitalares"),
    ("Consultoria", "consultoria técnica"), ("Limpeza", "limpeza e conservação"), ("Segurança", "vigilância"),
    ("Papelaria", "material de escritório"), ("Eletrônicos", "equipamentos de informática"), ("Construções", "reforma de prédio"),
]
ORGAOS_ESTADO = [
    "SECRETARIA DE SAÚDE (FICTÍCIA)", "SECRETARIA DE EDUCAÇÃO (FICTÍCIA)", "SECRETARIA DE SEGURANÇA (FICTÍCIA)",
    "SECRETARIA DE INFRAESTRUTURA (FICTÍCIA)", "SECRETARIA DE ADMINISTRAÇÃO (FICTÍCIA)", "SECRETARIA DE TRANSPORTES (FICTÍCIA)",
    "SECRETARIA DE AGRICULTURA (FICTÍCIA)", "SECRETARIA DE CULTURA (FICTÍCIA)", "SECRETARIA DE TURISMO (FICTÍCIA)",
    "SECRETARIA DE ESPORTES (FICTÍCIA)", "SECRETARIA DE MEIO AMBIENTE (FICTÍCIA)", "SECRETARIA DE HABITAÇÃO (FICTÍCIA)",
]
ORGAOS_GARANHUNS = ["SECRETARIA MUNICIPAL DE OBRAS (FICTÍCIA)", "SECRETARIA MUNICIPAL DE SAÚDE (FICTÍCIA)", "SECRETARIA MUNICIPAL DE EDUCAÇÃO (FICTÍCIA)"]
N_ESTADO, N_GARANHUNS = 84, 36
N_FORNECEDORES, N_CRUZADOS, N_SANCIONADOS, N_EXECUCOES = 44, 8, 18, 26


def brl(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def slug(texto: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in texto.split("(")[0]).strip("-").replace("--", "-")


def main() -> None:
    rng = random.Random(20261106)
    BRUTO.mkdir(parents=True, exist_ok=True)
    PASTA.mkdir(parents=True, exist_ok=True)

    # Fornecedores. Os 8 primeiros atendem os dois entes.
    forn = []
    for i, palavra in enumerate(PALAVRAS[:N_FORNECEDORES]):
        ramo = RAMOS[i % len(RAMOS)]
        cnpj = f"9{i + 1:07d}0001{(i * 7) % 90 + 10:02d}"
        forn.append({"id": f"cnpj:{cnpj}", "cnpj": cnpj, "nome": f"{palavra} {ramo[0]} Ltda (fictícia)", "objeto": ramo[1]})

    # Valores únicos, para o maior contrato e os "maior de cada órgão" não empatarem.
    valores = rng.sample(range(10_500, 4_900_000), N_ESTADO + N_GARANHUNS)
    valores = [v + rng.choice([0.0, 0.25, 0.5, 0.75]) for v in valores]

    evidencias, contratos, processos = [], [], []
    linhas_bruto = []

    def evidencia(prefixo: str, ente: str, trecho: str) -> str:
        n = len(linhas_bruto) + 1
        linhas_bruto.append(trecho)
        eid = f"{prefixo}{n}"
        evidencias.append({"id": eid, "documento_hash": "", "arquivo": ARQUIVO, "tabela": "benchmark", "linha": n,
                           "trecho": trecho, "url": URL, "capturado_em": CAPTURA, "tenant": ente, "trecho_mascarado": False})
        return eid

    def unidades(ente: str) -> list[dict]:
        nomes = ORGAOS_ESTADO if ente == "pe-estado" else ORGAOS_GARANHUNS
        return [{"uj": f"{ente}:uj:{slug(n)}", "uj_nome": n} for n in nomes]

    # Contratos: um fornecedor "do ente" por contrato; os cruzados aparecem nos dois.
    cruzados = forn[:N_CRUZADOS]
    so_estado = forn[N_CRUZADOS:N_CRUZADOS + 28]
    so_garanhuns = forn[N_CRUZADOS + 28:]
    escolha = {
        "pe-estado": [cruzados[i % N_CRUZADOS] for i in range(N_CRUZADOS)] + [so_estado[i % len(so_estado)] for i in range(N_ESTADO - N_CRUZADOS)],
        "pe-garanhuns": [cruzados[i % N_CRUZADOS] for i in range(N_CRUZADOS)] + [so_garanhuns[i % len(so_garanhuns)] for i in range(N_GARANHUNS - N_CRUZADOS)],
    }
    rng.shuffle(escolha["pe-estado"])
    rng.shuffle(escolha["pe-garanhuns"])

    numero, idx_valor, forn_evid = 0, 0, {}
    for ente, quantidade in (("pe-estado", N_ESTADO), ("pe-garanhuns", N_GARANHUNS)):
        ujs = unidades(ente)
        for k in range(quantidade):
            numero += 1
            f = escolha[ente][k]
            uj = ujs[k % len(ujs)]
            valor = valores[idx_valor]
            idx_valor += 1
            ano = rng.choice([2025, 2026])
            num = f"{numero}/{ano}"
            processo = None
            if ente == "pe-garanhuns" and k % 3 != 2:
                pid = f"{ente}:licitacao:{k + 1}"
                pev = evidencia("p", ente, f"DADO FICTÍCIO. Pregão {k + 1}/{ano}, {f['objeto']}, estimado R$ {brl(valor * 1.1)}")
                processos.append({"id": pid, "cod": str(k + 1), "numero": f"{k + 1}/{ano}", "modalidade": "Pregao Eletronico",
                                  "data": f"{ano}-0{rng.randint(1, 3)}-1{rng.randint(0, 9)}", "descricao": f["objeto"].capitalize() + " (fictício)",
                                  "fase": "Concluído", "valor_estimado": round(valor * 1.1, 2), "valor_homologado": valor,
                                  "tenant": ente, "sensibilidade": "publico", "evidencia": pev})
                processo = pid
            ev = evidencia("c", ente, f"DADO FICTÍCIO. Contrato {num}, {f['nome']}, {f['objeto']}, {uj['uj_nome']}, R$ {brl(valor)}")
            forn_evid.setdefault((f["id"], ente), ev)
            contratos.append({
                "inicio": f"{ano}-0{rng.randint(1, 9)}-01", "fim": f"{rng.choice([2026, 2027])}-{rng.randint(10, 12)}-{rng.randint(10, 28)}",
                "tem_aditivo": False, **uj, "tenant": ente, "sensibilidade": "publico", "id": f"{ente}:contrato:{numero}", "idc": str(numero),
                "numero": num, "objeto": f"{f['objeto'].capitalize()} (fictício)", "valor_contratado": valor,
                "processo_informado": processo is not None, "processo": processo, "fornecedor": f["id"], "evidencia": ev})

    fornecedores = [{"id": f["id"], "tipo": "PJ", "cnpj": f["cnpj"], "nome": f["nome"], "resolvido": True, "evidencia": ev, "tenant": ente}
                    for (fid, ente), ev in forn_evid.items() for f in forn if f["id"] == fid]

    # Sanções (todas do Estado): 18 fornecedores do Estado, de 1 a 7 ocorrências, parte em aberto.
    sancionaveis = [f for f in forn if (f["id"], "pe-estado") in forn_evid]
    sancoes, n_sancao = [], 0
    for i, f in enumerate(rng.sample(sancionaveis, N_SANCIONADOS)):
        for j in range(1 + (i * 3) % 7):
            n_sancao += 1
            tipo = rng.choice(["MULTA", "ADVERTÊNCIA", "SUSPENSÃO TEMPORÁRIA", "IMPEDIMENTO DE LICITAR"])
            situacao = "EM ABERTO" if rng.random() < 0.55 else "LIBERADA"
            pub = f"202{rng.randint(3, 5)}-{rng.randint(1, 12):02}-{rng.randint(10, 28)}"
            ev = evidencia("s", "pe-estado", f"DADO FICTÍCIO. {tipo}, {situacao}, {f['nome']}, publicada em {pub}")
            sancoes.append({"id": f"pe-estado:sancao:{n_sancao}", "tipo": tipo, "situacao": situacao, "publicada_em": pub,
                            "inicio_suspensao": None, "fim_suspensao": None, "orgao": rng.choice(ORGAOS_ESTADO),
                            "descricao": "Ocorrência fictícia para desenvolvimento", "fornecedor": f["id"], "tenant": "pe-estado",
                            "sensibilidade": "publico", "evidencia": ev})

    # Execução financeira: uma linha por fornecedor, sempre com os cruzados (o gabarito pergunta sobre eles).
    execucoes = []
    pagaveis = cruzados + [f for f in sancionaveis if f not in cruzados]
    for f in pagaveis[:N_EXECUCOES]:
        pago = float(rng.randint(2_000, 900_000))
        ano = rng.choice(["2024", "2025"])
        orgao = rng.choice(ORGAOS_ESTADO)
        ev = evidencia("e", "pe-estado", f"DADO FICTÍCIO. {ano}, {f['nome']}, {orgao}, pago R$ {brl(pago)}")
        execucoes.append({"id": f"pe-estado:execucao:{ano}:{f['cnpj']}:1", "ano": ano, "empenhado": pago, "liquidado": pago, "pago": pago,
                          "restos_a_pagar": 0.0, "orgao": orgao, "fornecedor": f["id"], "uj": f"pe-estado:uj:{slug(orgao)}",
                          "uj_nome": orgao, "tenant": "pe-estado", "sensibilidade": "publico", "evidencia": ev})
        if (f["id"], "pe-estado") not in forn_evid:
            forn_evid[(f["id"], "pe-estado")] = ev

    # O arquivo bruto só existe depois de todas as linhas; o hash vai para cada evidência.
    corpo = "\n".join(f"<tr><td>{n}</td><td>{escape(t)}</td></tr>" for n, t in enumerate(linhas_bruto, 1))
    html = f'<!doctype html>\n<html lang="pt-BR"><body>\n<p>DADOS FICTÍCIOS para o benchmark de desenvolvimento.</p>\n<table>\n{corpo}\n</table>\n</body></html>\n'
    (BRUTO / ARQUIVO).write_text(html, encoding="utf-8", newline="\n")
    h = hashlib.sha256((BRUTO / ARQUIVO).read_bytes()).hexdigest()
    for e in evidencias:
        e["documento_hash"] = h

    conjuntos = {"contratos": contratos, "evidencias": evidencias, "fornecedores": fornecedores,
                 "processos": processos, "sancoes": sancoes, "execucoes": execucoes}
    for nome, itens in conjuntos.items():
        (PASTA / f"{nome}.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in itens), encoding="utf-8", newline="\n")
    print(f"hash do arquivo bruto: {h}")
    print({k: len(v) for k, v in conjuntos.items()})


if __name__ == "__main__":
    main()
