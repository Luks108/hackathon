"""NFC-e: QR code (ou chave de acesso) → itens da nota, direto da SEFAZ.

Pernambuco (UF 26) devolve o XML completo da nota (nfeProc) na URL do próprio QR, sem captcha
(medido em 01/11/2026: ~0,3 s). Outros estados exibem HTML diferente por UF — para eles, devolvemos
o erro e o fallback é o Opus ler o cupom impresso na foto.

    inferencia/.venv/bin/python inferencia/nfce.py "<texto do QR ou chave de 44 dígitos>"

LGPD: o CPF/nome do consumidor (bloco <dest>) nunca sai daqui — estoque não precisa dele.
"""

import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

NS = {"n": "http://www.portalfiscal.inf.br/nfe"}
CONSULTA_PE = "https://nfce.sefaz.pe.gov.br:444/nfce-web/consultarNFCe?p={chave}"

# Códigos de erro mais comuns da consulta (o resto volta só com o número).
ERROS = {
    "217": "nota não encontrada na SEFAZ (pode levar alguns minutos após a compra para aparecer)",
    "236": "chave de acesso inválida (dígito verificador não confere)",
    "100": "a SEFAZ não aceitou a consulta sem o código do QR (mande a foto do QR em vez da chave digitada)",
}


FORMAS = {"01": "dinheiro", "02": "cheque", "03": "cartão de crédito", "04": "cartão de débito", "05": "crédito loja",
          "10": "vale alimentação", "11": "vale refeição", "15": "boleto", "17": "PIX", "99": "outros"}


def param_p(texto: str) -> str | None:
    """Parâmetro `p` inteiro do QR (chave|versao|tpAmb|...|hash). A SEFAZ-PE exige o hash original
    quando o QR é versão 2: remontar com `|3|1` devolve erro 100."""
    m = re.search(r"[?&]p=(\d{44}[|][\w|.-]*)", texto)
    return m.group(1) if m else None


def chave_de(texto: str) -> str | None:
    """Extrai a chave de 44 dígitos do texto do QR (qualquer versão) ou de uma chave digitada com espaços."""
    m = re.search(r"[?&]p=(\d{44})", texto) or re.search(r"chNFe=(\d{44})", texto)
    if m:
        return m.group(1)
    digitos = re.sub(r"\D", "", texto)
    return digitos if len(digitos) == 44 else None


def _num(e: ET.Element | None, caminho: str) -> float:
    v = e.findtext(caminho, default="", namespaces=NS) if e is not None else ""
    return float(v) if v else 0.0


def consultar(texto_qr_ou_chave: str) -> dict:
    chave = chave_de(texto_qr_ou_chave)
    if not chave:
        return {"erro": "não encontrei uma chave de acesso de 44 dígitos nesse texto"}
    uf = chave[:2]
    if uf != "26":
        return {"erro": f"consulta automática só está pronta para PE (chave é da UF {uf}); leia os itens no cupom impresso",
                "chave": chave}

    # Com o QR em mãos, repassar o parâmetro `p` como veio (hash incluso); só a chave digitada usa |3|1.
    p = param_p(texto_qr_ou_chave) or f"{chave}|3|1"
    req = urllib.request.Request(CONSULTA_PE.format(chave=p), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raiz = ET.fromstring(r.read())

    erro = (raiz.findtext("n:erro", default="", namespaces=NS) or "").strip()
    if erro:
        return {"erro": ERROS.get(erro, f"SEFAZ devolveu erro {erro}"), "chave": chave}
    inf = raiz.find(".//n:infNFe", NS)
    if inf is None:
        return {"erro": "resposta da SEFAZ sem a nota (formato inesperado)", "chave": chave}

    emit = inf.find("n:emit", NS)
    ender = emit.find("n:enderEmit", NS)
    itens = []
    for det in inf.findall("n:det", NS):
        p = det.find("n:prod", NS)
        ean = p.findtext("n:cEAN", default="", namespaces=NS)
        bruto = _num(p, "n:vProd")
        desconto = _num(p, "n:vDesc")
        itens.append({
            "item": int(det.get("nItem")),
            "descricao": p.findtext("n:xProd", namespaces=NS),
            "quantidade": _num(p, "n:qCom"),
            "unidade": p.findtext("n:uCom", namespaces=NS),
            "valor_unit": round(_num(p, "n:vUnCom"), 2),
            "desconto": desconto,
            "valor_total": round(bruto - desconto, 2),
            "ean": ean if ean.isdigit() else None,
            "codigo_loja": p.findtext("n:cProd", namespaces=NS),
            "ncm": p.findtext("n:NCM", namespaces=NS),
        })

    protocolo = raiz.find(".//n:protNFe/n:infProt", NS)
    return {
        "chave": chave,
        "loja": {
            "nome": emit.findtext("n:xNome", namespaces=NS),
            "fantasia": emit.findtext("n:xFant", default="", namespaces=NS),
            "cnpj": emit.findtext("n:CNPJ", namespaces=NS),
            "endereco": f'{ender.findtext("n:xLgr", namespaces=NS)}, {int(ender.findtext("n:nro", default="0", namespaces=NS) or 0)}',
            "cidade": f'{ender.findtext("n:xMun", namespaces=NS)}-{ender.findtext("n:UF", namespaces=NS)}',
        },
        "emissao": inf.findtext("n:ide/n:dhEmi", namespaces=NS),
        "numero": inf.findtext("n:ide/n:nNF", namespaces=NS),
        "total": _num(inf, "n:total/n:ICMSTot/n:vNF"),
        "pagamento": [
            {"forma": FORMAS.get(d.findtext("n:tPag", namespaces=NS), d.findtext("n:tPag", namespaces=NS)),
             "valor": _num(d, "n:vPag")}
            for d in inf.findall("n:pag/n:detPag", NS)
        ],
        "situacao": protocolo.findtext("n:xMotivo", default="", namespaces=NS) if protocolo is not None else "",
        "itens": itens,
    }


if __name__ == "__main__":
    print(json.dumps(consultar(sys.argv[1]), ensure_ascii=False, indent=2))
