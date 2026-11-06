"""Transforma a captura bruta em fatos com evidência, sem nova coleta na rede.

    .venv/bin/python coleta/extrair.py

Regras:
- Todo fato aponta para uma Evidencia: hash do arquivo, tabela, linha e trecho.
- CPF nunca sai daqui. Pessoa física vira HMAC, e o nome é retirado do trecho.
- CNPJ inválido é tratado como dado pessoal: pode ser CPF preenchido com zeros.
"""

import csv
import functools
import hashlib
import hmac
import html
import io
import json
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in linha:
        k, v = linha.split("=", 1)
        os.environ.setdefault(k, v)

BRUTO = Path(os.environ["BRUTO"])
SAIDA = RAIZ / "dados"
CHAVE_PF = os.environ["CHAVE_PF"].encode()

GARANHUNS = "pe-garanhuns"
ESTADO = "pe-estado"
PORTAL = "https://portaltransparencia.app.br"
PAINEL_CONTRATOS = "https://transparencia.pe.gov.br/licitacoes-e-contratos/menu-contratos/painel-de-contratos/"
PAINEL_FORNECEDORES = "https://transparencia.pe.gov.br/licitacoes-e-contratos/fornecedores/consulta-fornecedores/"
CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CPF_CRU = re.compile(r"(?<!\d)\d{11}(?!\d)")
FISCAL = re.compile(r"Fiscal do Contrato:.*?(?=\s\d{2}/\d{2}/\d{4}\b|$)")


@functools.lru_cache(maxsize=None)
def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def texto(celula: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", celula))).strip()


def linhas_da_tabela(caminho: Path) -> list[str]:
    s = caminho.read_text(encoding="utf8", errors="replace")
    tabela = max(re.findall(r"<table\b.*?</table>", s, re.S | re.I), key=len)
    return re.findall(r"<tr\b.*?</tr>", tabela, re.S | re.I)[1:]


def celulas(linha: str) -> list[str]:
    return re.findall(r"<td\b.*?</td>", linha, re.S | re.I)


def sem_cpf(valor: str) -> str:
    """Razão social de MEI traz o CPF do titular colado no nome, sem pontuação."""
    valor = CPF.sub("[CPF]", valor)
    return CPF_CRU.sub(lambda m: "[CPF]" if cpf_valido(m[0]) else m[0], valor)


def sem_fiscal(valor: str) -> str:
    """O nome do fiscal vem colado no objeto do contrato e não interessa à análise do fornecedor."""
    return FISCAL.sub(" ", valor).strip()


def real(valor: str) -> float:
    """O portal mistura "208.748,30", "0.00" e "511.633.34": o último separador
    seguido de 1 ou 2 dígitos é o decimal; os demais são de milhar."""
    v = re.sub(r"[^\d,.]", "", valor)
    m = re.fullmatch(r"(.*)[.,](\d{1,2})", v)
    inteiro, decimal = (m[1], m[2]) if m else (v, "0")
    inteiro = re.sub(r"\D", "", inteiro)
    return float(f"{inteiro or 0}.{decimal}")


def data_br(valor: str) -> str | None:
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", valor.strip())
    return None if not m or m[3] == "1900" else f"{m[3]}-{m[2]}-{m[1]}"


def digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def cnpj_valido(d: str) -> bool:
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for n in (12, 13):
        pesos = list(range(n - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(int(a) * b for a, b in zip(d[:n], pesos))
        resto = soma % 11
        if int(d[n]) != (0 if resto < 2 else 11 - resto):
            return False
    return True


def cpf_valido(d: str) -> bool:
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        resto = sum(int(a) * b for a, b in zip(d[:n], range(n + 1, 1, -1))) * 10 % 11
        if int(d[n]) != resto % 10:
            return False
    return True


def documento(d: str) -> tuple[str, str]:
    """O painel do Estado guarda o documento como número e perde os zeros à esquerda.
    Na dúvida entre CNPJ e CPF, vale o CPF: errar para o lado de proteger o dado pessoal."""
    pf = len(d) <= 11 and cpf_valido(d.zfill(11))
    if cnpj_valido(d.zfill(14)) and not pf:
        return "PJ", d.zfill(14)
    return ("PF" if pf else "invalido"), d


def mascara_confere(mascara: str, doc: str) -> bool:
    return len(mascara) == len(doc) and all(m == "*" or m == d for m, d in zip(mascara, doc))


def pseudonimo(valor: str) -> str:
    return hmac.new(CHAVE_PF, valor.encode(), hashlib.sha256).hexdigest()[:24]


def evidencia(arquivo: Path, tabela: str, linha: int, trecho: str, url: str, tenant: str, mascarado=False,
              capturado_em="2026-11-05") -> dict:
    trecho = sem_cpf(trecho)
    h = sha256(arquivo)
    return {
        "id": f"{h[:16]}:{tabela}:{linha}",
        "documento_hash": h,
        "arquivo": arquivo.name,
        "tabela": tabela,
        "linha": linha,
        "trecho": trecho[:1500],
        "url": url,
        "capturado_em": capturado_em,
        "tenant": tenant,
        "trecho_mascarado": mascarado,
    }


def fiscais() -> dict[tuple, str]:
    """Documento completo por (número, início, fim, valor). Chave ambígua é descartada."""
    achados: dict[tuple, set[str]] = {}
    for linha in linhas_da_tabela(BRUTO / "fiscais-2026-SENSIVEL.html"):
        c = [texto(x) for x in celulas(linha)]
        if len(c) < 4:
            continue
        doc = re.search(r"CPF/CNPJ: (\S+)", c[1])
        vig = re.findall(r"\d{2}/\d{2}/\d{4}", c[3])
        if doc and len(vig) == 2:
            achados.setdefault((c[0], vig[0], vig[1], real(c[2])), set()).add(doc[1])
    return {k: next(iter(v)) for k, v in achados.items() if len(v) == 1}


def fornecedor_de(mascara: str, nome: str, completo: str | None, relatorio: dict) -> dict:
    d = digitos(completo) if completo and mascara_confere(mascara, completo) else ""
    if completo and not d:
        relatorio["mascara_divergente"] += 1
    if len(d) == 14:
        relatorio["pj_resolvido"] += 1
        return {"id": f"cnpj:{d}", "tipo": "PJ", "cnpj": d, "nome": nome, "resolvido": True}
    if len(d) == 11:
        relatorio["pf_resolvido"] += 1
        return {"id": f"pf:{pseudonimo(d.lstrip('0'))}", "tipo": "PF", "cnpj": None, "nome": None, "resolvido": True}
    if "/" in mascara:
        relatorio["pj_sem_documento"] += 1
        return {"id": f"pj-nome:{pseudonimo(nome.upper())}", "tipo": "PJ", "cnpj": None, "nome": nome, "resolvido": False}
    relatorio["pf_sem_documento"] += 1
    return {"id": f"pf-nome:{pseudonimo(mascara + nome.upper())}", "tipo": "PF", "cnpj": None, "nome": None, "resolvido": False}


def extrair_contratos(saida: dict, relatorio: dict) -> None:
    arquivo = BRUTO / "contratos-2026.html"
    docs = fiscais()
    for n, linha in enumerate(linhas_da_tabela(arquivo), 1):
        c = celulas(linha)
        idc = re.search(r"idc=(\d+)", linha)
        cab = re.search(r"Nº (\S+) CPF/CNPJ: (\S+) (.*?) UJ: (.*)", texto(c[0])) if len(c) >= 5 else None
        if not idc or not cab:
            relatorio["contrato_fora_do_padrao"] += 1
            continue
        numero, mascara, nome, uj = cab[1], cab[2], cab[3], cab[4]
        vig = re.findall(r"\d{2}/\d{2}/\d{4}", texto(c[2]))
        valor = real(texto(c[4]))
        chave = (numero, vig[0], vig[1], valor) if len(vig) == 2 else None
        forn = fornecedor_de(mascara, nome, docs.get(chave), relatorio)
        pf = forn["tipo"] == "PF"
        bruto = sem_fiscal(texto(linha))
        objeto = sem_fiscal(sem_cpf(texto(c[1])))
        if pf:
            bruto = re.sub(re.escape(nome), "[pessoa física]", bruto, flags=re.I).replace(mascara, "[documento]")
            objeto = re.sub(re.escape(nome), "[pessoa física]", objeto, flags=re.I)
        cod = re.search(r"exibeLicitacao\.aspx\?p_i=64&amp;cod=(\d+)", linha)
        ev = evidencia(arquivo, "contratos", n, bruto, f"{PORTAL}/frmConsultaContrato.aspx?p_i=64&p_t=0", GARANHUNS, True)
        saida["evidencias"].append(ev)
        saida["fornecedores"].append({**forn, "evidencia": ev["id"], "tenant": GARANHUNS})
        saida["contratos"].append({
            "id": f"{GARANHUNS}:contrato:{idc[1]}",
            "idc": idc[1],
            "numero": numero,
            "objeto": objeto,
            "inicio": data_br(vig[0]) if vig else None,
            "fim": data_br(vig[1]) if len(vig) == 2 else None,
            "valor_contratado": valor,
            "tem_aditivo": not re.search(r"Aditivo: 0\b", texto(c[3])),
            "processo_informado": bool(cod),
            "processo": f"{GARANHUNS}:licitacao:{cod[1]}" if cod else None,
            "fornecedor": forn["id"],
            "uj": f"{GARANHUNS}:uj:{pseudonimo(uj)[:12]}",
            "uj_nome": uj,
            "tenant": GARANHUNS,
            "sensibilidade": "pessoal" if pf else "publico",
            "evidencia": ev["id"],
        })


def extrair_licitacoes(saida: dict, relatorio: dict) -> None:
    arquivo = BRUTO / "licitacoes-2026.html"
    for n, linha in enumerate(linhas_da_tabela(arquivo), 1):
        c = [texto(x) for x in celulas(linha)]
        cod = re.search(r"cod=(\d+)", linha)
        m = re.search(r"Processo: (\S+) / (\d{4}) (.+?) \S+ / \d{4} Data: (\S+)", c[1]) if len(c) >= 4 else None
        if not cod or not m:
            relatorio["licitacao_fora_do_padrao"] += 1
            continue
        fase = re.search(r"Fase: (.*?) Estimado: (.*?) Homologado: (.*)", c[3])
        ev = evidencia(arquivo, "licitacoes", n, " ".join(c), f"{PORTAL}/retornaDadosLicitacao.aspx?p_i=64&p_t=0", GARANHUNS)
        saida["evidencias"].append(ev)
        saida["processos"].append({
            "id": f"{GARANHUNS}:licitacao:{cod[1]}",
            "cod": cod[1],
            "numero": f"{m[1]}/{m[2]}",
            "modalidade": m[3],
            "data": m[4],
            "descricao": sem_cpf(c[2]),
            "fase": fase[1] if fase else None,
            "valor_estimado": real(fase[2]) if fase else None,
            "valor_homologado": real(fase[3]) if fase else None,
            "tenant": GARANHUNS,
            "sensibilidade": "publico",
            "evidencia": ev["id"],
        })


def maiusculas(valor) -> str:
    """O painel aplica maiúsculas sem tratar acento ("AGêNCIA"): corrigimos só a caixa."""
    return re.sub(r"\s+", " ", str(valor or "")).strip().upper()


def extrair_contratos_estado(saida: dict, relatorio: dict, sensiveis: set[str]) -> None:
    for arquivo in sorted(BRUTO.glob("pe-contratos-20??.json")):
        bruto = json.loads(arquivo.read_text(encoding="utf-8"))
        processos: set[str] = set()
        for n, r in enumerate(bruto["linhas"], 1):
            ug, numero, objeto, _, situacao, processo, credor, inicio, fim, valor, link = r
            ug = maiusculas(ug)
            doc, _, nome = str(credor or "").partition(" - ")
            tipo, d = documento(digitos(doc))
            relatorio[f"estado_{tipo.lower()}"] += 1
            pj = tipo == "PJ"
            if not pj:
                sensiveis.add(d)
            nome = maiusculas(nome)
            forn = {"id": f"cnpj:{d}", "tipo": "PJ", "cnpj": d, "nome": nome, "resolvido": True} if pj else \
                {"id": f"pf:{pseudonimo(d.lstrip('0'))}", "tipo": "PF", "cnpj": None, "nome": None, "resolvido": tipo == "PF"}
            objeto = maiusculas(objeto)
            if not pj and nome:
                objeto = re.sub(re.escape(nome), "[pessoa física]", objeto, flags=re.I)
            pdf = re.search(r'href="(https://transparencia\.pe\.gov\.br/contratos/[^"]+)"', str(link or ""))
            trecho = " | ".join(str(x) for x in (ug, numero, objeto, maiusculas(situacao), f"Processo {processo or 'não informado'}",
                                                 f"{d} - {nome}" if pj else "[pessoa física]", f"{inicio} a {fim}", f"R$ {valor}"))
            ev = evidencia(arquivo, "contratos", n, trecho, pdf[1] if pdf and pj else PAINEL_CONTRATOS, ESTADO, not pj, bruto["coletado_em"])
            uj = f"{ESTADO}:uj:{pseudonimo(ug)[:12]}"
            proc = f"{ESTADO}:processo:{pseudonimo(ug)[:12]}:{processo}" if processo else None
            saida["evidencias"].append(ev)
            saida["fornecedores"].append({**forn, "evidencia": ev["id"], "tenant": ESTADO})
            if proc and proc not in processos:
                processos.add(proc)
                saida["processos"].append({
                    "id": proc, "cod": None, "numero": str(processo), "modalidade": None, "data": None, "descricao": None,
                    "fase": None, "valor_estimado": None, "valor_homologado": None, "tenant": ESTADO,
                    "sensibilidade": "publico", "evidencia": ev["id"],
                })
            saida["contratos"].append({
                "id": f"{ESTADO}:contrato:{pseudonimo(ug)[:12]}:{numero}",
                "idc": None,
                "numero": numero,
                "objeto": objeto,
                "situacao": maiusculas(situacao),
                "inicio": inicio,
                "fim": fim,
                "valor_contratado": float(valor or 0),
                "tem_aditivo": None,       # o painel não informa aditivo
                "processo_informado": bool(processo),
                "processo": proc,
                "fornecedor": forn["id"],
                "uj": uj,
                "uj_nome": ug,
                "tenant": ESTADO,
                "sensibilidade": "publico" if pj else "pessoal",
                "evidencia": ev["id"],
            })


def extrair_execucao(saida: dict, relatorio: dict) -> None:
    """Agregado por fornecedor, órgão e ano. O portal não liga estes valores a um contrato."""
    for arquivo in sorted(BRUTO.glob("pe-execucao-20??.json")):
        bruto = json.loads(arquivo.read_text(encoding="utf-8"))
        ano = bruto["ano"]
        n = 0
        for consultado, linhas in bruto["por_documento"].items():
            alvo = consultado.zfill(14)
            for credor, ug, empenhado, liquidado, pago, restos, *_ in linhas:
                n += 1
                d = digitos(str(credor).split(" - ")[0]).zfill(14)
                if d != alvo:          # a busca do painel é por trecho: pode trazer outro credor
                    relatorio["execucao_outro_credor"] += 1
                    continue
                ug = maiusculas(ug)
                valores = dict(empenhado=float(empenhado or 0), liquidado=float(liquidado or 0), pago=float(pago or 0),
                               restos_a_pagar=float(restos or 0))
                trecho = f"{ano} | {credor} | {ug} | " + " | ".join(f"{k}: R$ {v:.2f}" for k, v in valores.items())
                ev = evidencia(arquivo, "execucao", n, trecho, PAINEL_FORNECEDORES, ESTADO, capturado_em=bruto["coletado_em"])
                saida["evidencias"].append(ev)
                saida["execucoes"].append({
                    "id": f"{ESTADO}:execucao:{ano}:{d}:{pseudonimo(ug)[:12]}",
                    "ano": ano, **valores, "orgao": ug,
                    "fornecedor": f"cnpj:{d}",
                    "uj": f"{ESTADO}:uj:{pseudonimo(ug)[:12]}",
                    "uj_nome": ug,
                    "tenant": ESTADO,
                    "sensibilidade": "publico",
                    "evidencia": ev["id"],
                })


def extrair_sancoes(saida: dict, relatorio: dict) -> None:
    """O CSV repete a ocorrência por telefone e endereço: uma linha por FORNOCORR_CD."""
    arquivo = BRUTO / "pe-sancionados.csv"
    conteudo = arquivo.read_text(encoding="utf-8-sig")
    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=";" if conteudo[:300].count(";") > 5 else ",")
    vistos: set[str] = set()
    nulo = lambda v: None if v in ("", "<NULL>") else v  # noqa: E731
    url = "https://transparencia.pe.gov.br/licitacoes-e-contratos/fornecedores/fornecedores-sancionados/"
    for n, r in enumerate(leitor, 2):
        cod = r["FORNOCORR_CD"]
        if cod in vistos:
            relatorio["sancao_linha_repetida"] += 1
            continue
        vistos.add(cod)
        d = digitos(r["PESSDOC_NU_DOCUMENTO"])
        pj = cnpj_valido(d)
        nome = r["PESSOA_NM_RAZAO_SOCIAL"] if pj else None
        relatorio["sancao_pj" if pj else "sancao_documento_nao_cnpj"] += 1
        forn = {
            "id": f"cnpj:{d}" if pj else f"pf:{pseudonimo(d.lstrip('0'))}",
            "tipo": "PJ" if pj else "PF",
            "cnpj": d if pj else None,
            "nome": nome,
            "resolvido": True,
        }
        trecho = " | ".join(filter(None, [r["GBPTPOCORR_NM"], r["SITUACAO_OCORRENCIA"], nome, r["FORNOCORR_DS"]]))
        ev = evidencia(arquivo, "sancoes", n, trecho, url, ESTADO, not pj)
        saida["evidencias"].append(ev)
        saida["fornecedores"].append({**forn, "evidencia": ev["id"], "tenant": ESTADO})
        saida["sancoes"].append({
            "id": f"{ESTADO}:sancao:{cod}",
            "tipo": r["GBPTPOCORR_NM"],
            "situacao": r["SITUACAO_OCORRENCIA"],
            "publicada_em": nulo(r["FORNOCORR_DT_PUBLIC_DOE"]),
            "inicio_suspensao": nulo(r["FORNOCORR_DT_INICIO_SUSPENSAO"]),
            "fim_suspensao": nulo(r["FORNOCORR_DT_FIM_SUSPENSAO"]),
            "orgao": r["UG_DS"],
            "descricao": sem_cpf(r["FORNOCORR_DS"]) if pj else None,
            "fornecedor": forn["id"],
            "tenant": ESTADO,
            "sensibilidade": "publico" if pj else "pessoal",
            "evidencia": ev["id"],
        })


def main() -> int:
    SAIDA.mkdir(exist_ok=True)
    saida = {k: [] for k in ("contratos", "processos", "fornecedores", "sancoes", "execucoes", "evidencias")}
    relatorio: dict = {k: 0 for k in (
        "pj_resolvido", "pf_resolvido", "pj_sem_documento", "pf_sem_documento", "mascara_divergente",
        "contrato_fora_do_padrao", "licitacao_fora_do_padrao", "sancao_linha_repetida", "sancao_pj",
        "sancao_documento_nao_cnpj", "estado_pj", "estado_pf", "estado_invalido", "execucao_outro_credor",
    )}
    sensiveis: set[str] = set()
    extrair_contratos(saida, relatorio)
    extrair_licitacoes(saida, relatorio)
    extrair_contratos_estado(saida, relatorio, sensiveis)
    extrair_sancoes(saida, relatorio)
    extrair_execucao(saida, relatorio)

    for f in saida["fornecedores"]:
        f["nome"] = sem_cpf(f["nome"]) if f["nome"] else None

    bruto = json.dumps(saida, ensure_ascii=False)
    numeros = set(re.findall(r"\d{9,14}", bruto))
    if CPF.search(bruto) or numeros & {d for d in sensiveis if len(d) >= 9}:
        print("ERRO: CPF no resultado; nada foi gravado", file=sys.stderr)
        return 1
    for nome, itens in saida.items():
        (SAIDA / f"{nome}.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in itens))
    print(json.dumps({**{k: len(v) for k, v in saida.items()}, "relatorio": relatorio}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
