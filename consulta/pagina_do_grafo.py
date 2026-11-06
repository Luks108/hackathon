"""Gera a página do grafo direto do Neo4j. Nenhum número é digitado aqui.

    .venv/bin/python consulta/pagina_do_grafo.py <saida.html>

Publica o que um perfil sem acesso a dados pessoais veria: pessoa física fica de fora.
"""

import json
import os
import re
import sys
from pathlib import Path

from neo4j import GraphDatabase

RAIZ = Path(__file__).resolve().parents[1]
for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in linha:
        k, v = linha.split("=", 1)
        os.environ.setdefault(k, v)

CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")


def rotulo(tipo: str, p: dict) -> str:
    if tipo == "Contrato":
        return "Contrato " + re.sub(r"^0+", "", p.get("numero", ""))
    if tipo == "ProcessoLicitatorio":
        return "Processo " + p.get("numero", "")
    if tipo == "Sancao":
        return (p.get("tipo") or "Sanção").split(" ")[0].capitalize()
    if tipo == "ExecucaoFinanceira":
        return f'Execução {p.get("ano")}'
    if tipo == "Evidencia":
        return f'{p.get("tabela")}, linha {p.get("linha")}'
    return p.get("nome") or p.get("id", "")


def ler_grafo() -> dict:
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=("neo4j", os.environ["NEO4J_SENHA"]))
    with driver.session() as s:
        nos = {r["id"]: {"id": r["id"], "t": r["t"], "p": r["p"]} for r in s.run(
            "MATCH (n) RETURN elementId(n) AS id, labels(n)[0] AS t, properties(n) AS p")}
        arestas = [dict(r) for r in s.run(
            "MATCH (a)-[r]->(b) RETURN elementId(a) AS a, elementId(b) AS b, type(r) AS rel")]
    driver.close()

    # Na tela fica a maior linha por fornecedor e ano. O agente continua consultando todas.
    maiores: dict[tuple, str] = {}
    for e in arestas:
        if e["rel"] == "TEM_EXECUCAO":
            chave = (e["a"], nos[e["b"]]["p"]["ano"])
            if chave not in maiores or nos[e["b"]]["p"]["pago"] > nos[maiores[chave]]["p"]["pago"]:
                maiores[chave] = e["b"]
    for i in [i for i, n in nos.items() if n["t"] == "ExecucaoFinanceira" and i not in maiores.values()]:
        del nos[i]
    arestas = [e for e in arestas if e["a"] in nos and e["b"] in nos]

    def visivel(n: dict) -> bool:
        p = n["p"]
        return p.get("sensibilidade", "publico") == "publico" and p.get("tipo") != "PF"

    fatos = {i for i, n in nos.items() if n["t"] != "Evidencia" and visivel(n)}
    provas = {e["b"] for e in arestas if e["rel"] == "PROVADO_POR" and e["a"] in fatos}
    # Evidência de fato oculto não entra, mesmo quando também prova um fornecedor visível.
    ocultas = {e["b"] for e in arestas if e["rel"] == "PROVADO_POR" and e["a"] not in fatos}
    manter = fatos | (provas - ocultas)

    saida = [
        {"id": i, "t": n["t"], "r": rotulo(n["t"], n["p"]), "p": n["p"]}
        for i, n in nos.items() if i in manter
    ]
    ligacoes = [e for e in arestas if e["a"] in manter and e["b"] in manter]
    return {"nos": saida, "arestas": ligacoes}


MOLDE = r"""<title>Grafo de Fornecedores</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=Zilla+Slab:wght@500;600&display=swap">
<style>
/* Layout: grafo como peça principal, com painel da evidência ao lado. Paleta do site do Nomos. */
:root {
  --tinta:#16211f; --tinta-70:#46534f; --tinta-45:#68726e;
  --papel:#f7f6f3; --papel-2:#edece6; --regra:#d6d3c9;
  --latao:#8f6428; --latao-fraco:#f0e6d5; --ruim:#a3372a;
  --Contrato:#3f7fc2; --Fornecedor:#3d9a78; --Sancao:#c2603f; --ProcessoLicitatorio:#8a6dba;
  --UnidadeJurisdicionada:#b5801f; --Ente:#54707d; --Evidencia:#9a978b; --ExecucaoFinanceira:#2a8c8c;
  --serif:"Source Serif 4",Georgia,serif; --slab:"Zilla Slab",Rockwell,Georgia,serif;
  --mono:"IBM Plex Mono",Consolas,monospace;
}
@media (prefers-color-scheme:dark) { :root:not([data-theme="light"]) {
  --tinta:#eceae3; --tinta-70:#b0aca1; --tinta-45:#938f85;
  --papel:#141a19; --papel-2:#1d2423; --regra:#303735;
  --latao:#d3a35c; --latao-fraco:#2a2318; --ruim:#e0796a;
  --Contrato:#6ea8e0; --Fornecedor:#62c29d; --Sancao:#e0876a; --ProcessoLicitatorio:#b39ae0;
  --UnidadeJurisdicionada:#d9a648; --Ente:#8caab8; --Evidencia:#a8a598;
  color-scheme:dark;
} }
:root[data-theme="dark"] {
  --tinta:#eceae3; --tinta-70:#b0aca1; --tinta-45:#938f85;
  --papel:#141a19; --papel-2:#1d2423; --regra:#303735;
  --latao:#d3a35c; --latao-fraco:#2a2318; --ruim:#e0796a;
  --Contrato:#6ea8e0; --Fornecedor:#62c29d; --Sancao:#e0876a; --ProcessoLicitatorio:#b39ae0;
  --UnidadeJurisdicionada:#d9a648; --Ente:#8caab8; --Evidencia:#a8a598;
  color-scheme:dark;
}
* { box-sizing:border-box; }
body { background:var(--papel); color:var(--tinta); font:17px/1.55 var(--serif); }
.folha { max-width:1240px; margin:0 auto; display:grid; gap:24px; padding-block:40px;
  padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); }
.olho { font:500 13px var(--mono); letter-spacing:.06em; color:var(--latao); margin:0 0 8px; }
h1 { font:600 clamp(32px,5vw,50px)/1.08 var(--slab); margin:0 0 10px; text-wrap:balance; }
.lide { margin:0; max-width:68ch; color:var(--tinta-70); }
.numeros { display:flex; flex-wrap:wrap; gap:8px 28px; font:400 14px var(--mono); color:var(--tinta-70); margin:0; padding:12px 0; border-block:1px solid var(--regra); list-style:none; }
.numeros b { color:var(--tinta); font-weight:500; font-variant-numeric:tabular-nums; }
.mesa { display:grid; grid-template-columns:minmax(0,1fr) 340px; gap:20px; align-items:stretch; }
.quadro { background:var(--papel-2); border:1px solid var(--regra); border-radius:4px; min-width:0; display:flex; flex-direction:column; }
canvas { display:block; width:100%; height:620px; cursor:grab; touch-action:pan-y; }
canvas:focus-visible, button:focus-visible, input:focus-visible { outline:2px solid var(--latao); outline-offset:2px; }
.legenda { display:flex; flex-wrap:wrap; gap:6px 14px; padding:10px 14px; border-top:1px solid var(--regra); font:400 13px var(--mono); margin:0; }
.legenda label { display:inline-flex; align-items:center; gap:7px; cursor:pointer; }
.pino { width:11px; height:11px; border-radius:50%; flex:none; }
.painel { border:1px solid var(--regra); border-radius:4px; padding:18px; min-width:0; overflow-wrap:anywhere; display:flex; flex-direction:column; gap:12px; }
.painel h2 { font:600 23px/1.2 var(--slab); margin:0; }
.tipo { font:500 12px var(--mono); letter-spacing:.05em; color:var(--latao); margin:0; }
dl { margin:0; display:grid; gap:9px; }
dt { font:400 12px var(--mono); color:var(--tinta-45); }
dd { margin:0; font-size:16px; line-height:1.4; }
.trecho { background:var(--latao-fraco); padding:10px 12px; font-size:15px; }
.ligado { display:flex; flex-wrap:wrap; gap:6px; }
.ligado button { font:400 12px var(--mono); padding:5px 8px; color:var(--tinta); background:none; border:1px solid var(--regra); border-radius:3px; cursor:pointer; text-align:left; }
.ligado button:hover { border-color:var(--latao); }
.nota { font-size:15px; color:var(--tinta-70); max-width:76ch; margin:0; }
.nota b { color:var(--tinta); }
@media (max-width:860px) { .mesa { grid-template-columns:minmax(0,1fr); } canvas { height:440px; } }
</style>

<main class="folha">
  <header>
    <p class="olho">HACK GARANHUNS TECH · DESAFIO 1</p>
    <h1>O grafo de fornecedores</h1>
    <p class="lide">Amostra de contratos de Garanhuns ligada às sanções do Estado de Pernambuco. Arraste os pontos, clique em um deles e siga até a evidência.</p>
  </header>
  <ul class="numeros" id="numeros"></ul>
  <section class="mesa" aria-label="Grafo">
    <div class="quadro">
      <canvas id="tela" tabindex="0" role="img" aria-label="Grafo de contratos, fornecedores, processos, sanções e evidências"></canvas>
      <div class="legenda" id="legenda"></div>
    </div>
    <aside class="painel" id="painel" aria-live="polite"></aside>
  </section>
  <p class="nota"><b>Como ler.</b> Ocorrência em aberto não prova irregularidade. O cadastro de sanções é de 05/06/2025, e a captura do portal é de 05/11/2026. Pagamentos ainda não foram coletados. Registros de pessoa física ficam fora desta visão.</p>
</main>

<script>
var DADOS = __DADOS__;
var NOME = { Contrato:"Contrato", Fornecedor:"Fornecedor", Sancao:"Sanção", ProcessoLicitatorio:"Processo", UnidadeJurisdicionada:"Unidade", Ente:"Ente público", Evidencia:"Evidência" };
var TAMANHO = { Ente:15, Fornecedor:11, Contrato:9, ProcessoLicitatorio:8, UnidadeJurisdicionada:8, Sancao:6, Evidencia:4 };
var ORDEM = ["Fornecedor","Contrato","Sancao","ProcessoLicitatorio","UnidadeJurisdicionada","Ente","Evidencia"];
var VERBO = { CONTRATA:"contrata", DECORRE_DE:"decorre de", CELEBRADO_POR:"celebrado por", PERTENCE_A:"pertence a", RECEBEU:"recebeu", DO_ENTE:"do ente", APARECE_EM:"aparece em", PROVADO_POR:"provado por" };
var visiveis = {}; ORDEM.forEach(function (t) { visiveis[t] = t !== "Evidencia"; });
var nos = DADOS.nos.map(function (n) { return Object.assign({}, n, { x:0, y:0, vx:0, vy:0 }); });
var porId = {}; nos.forEach(function (n) { porId[n.id] = n; });
var arestas = DADOS.arestas.filter(function (e) { return porId[e.a] && porId[e.b]; })
  .map(function (e) { return { a:porId[e.a], b:porId[e.b], rel:e.rel }; });

var tela = document.getElementById("tela"), ctx = tela.getContext("2d");
var L = 800, A = 620, escala = 1, selecionado = null, preso = null, sobre = null, movendo = false, quadros = 0;
var calmo = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function ativo(n) { return visiveis[n.t]; }
function medir() {
  var r = tela.getBoundingClientRect(); L = r.width || 800; A = r.height || 620;
  escala = window.devicePixelRatio || 1;
  tela.width = L * escala; tela.height = A * escala;
}
function semear() {
  nos.forEach(function (n, i) {
    var ang = i * 2.399963, raio = 40 + 13 * Math.sqrt(i) * 3;
    n.x = L / 2 + Math.cos(ang) * raio; n.y = A / 2 + Math.sin(ang) * raio * .8;
  });
}
function passo() {
  var vivos = nos.filter(ativo);
  for (var i = 0; i < vivos.length; i++) for (var j = i + 1; j < vivos.length; j++) {
    var a = vivos[i], b = vivos[j], dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy + .01;
    if (d2 > 90000) continue;
    var f = 2600 / d2; dx *= f / Math.sqrt(d2); dy *= f / Math.sqrt(d2);
    a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy;
  }
  arestas.forEach(function (e) {
    if (!ativo(e.a) || !ativo(e.b)) return;
    var dx = e.b.x - e.a.x, dy = e.b.y - e.a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
    var alvo = e.rel === "PROVADO_POR" ? 34 : e.rel === "RECEBEU" ? 46 : 92, f = (d - alvo) * .02;
    dx *= f / d; dy *= f / d; e.a.vx += dx; e.a.vy += dy; e.b.vx -= dx; e.b.vy -= dy;
  });
  vivos.forEach(function (n) {
    n.vx += (L / 2 - n.x) * .004; n.vy += (A / 2 - n.y) * .006;
    n.vx *= .82; n.vy *= .82;
    if (n !== preso) { n.x += n.vx; n.y += n.vy; }
    n.x = Math.max(26, Math.min(L - 26, n.x)); n.y = Math.max(22, Math.min(A - 22, n.y));
  });
}
function cor(nome) { return getComputedStyle(document.documentElement).getPropertyValue(nome).trim(); }
function vizinhos(n) {
  var s = {}; arestas.forEach(function (e) { if (e.a === n) s[e.b.id] = 1; if (e.b === n) s[e.a.id] = 1; }); return s;
}
function desenhar() {
  var paleta = {}; ORDEM.forEach(function (t) { paleta[t] = cor("--" + t); });
  var tinta = cor("--tinta"), regra = cor("--tinta-45"), fundo = cor("--papel-2"), foco = selecionado || sobre, viz = foco ? vizinhos(foco) : null;
  ctx.setTransform(escala, 0, 0, escala, 0, 0); ctx.clearRect(0, 0, L, A);
  arestas.forEach(function (e) {
    if (!ativo(e.a) || !ativo(e.b)) return;
    var perto = foco && (e.a === foco || e.b === foco);
    ctx.globalAlpha = foco ? (perto ? .9 : .1) : .34; ctx.strokeStyle = perto ? tinta : regra; ctx.lineWidth = perto ? 1.5 : 1;
    ctx.beginPath(); ctx.moveTo(e.a.x, e.a.y); ctx.lineTo(e.b.x, e.b.y); ctx.stroke();
  });
  nos.filter(ativo).forEach(function (n) {
    var perto = !foco || n === foco || viz[n.id]; ctx.globalAlpha = perto ? 1 : .2;
    ctx.beginPath(); ctx.arc(n.x, n.y, TAMANHO[n.t], 0, 6.2832); ctx.fillStyle = paleta[n.t]; ctx.fill();
    if (n === selecionado) { ctx.lineWidth = 2.5; ctx.strokeStyle = tinta; ctx.stroke(); }
  });
  ctx.font = "12px 'IBM Plex Mono', Consolas, monospace"; ctx.textAlign = "center"; ctx.lineJoin = "round";
  nos.filter(ativo).forEach(function (n) {
    var fixo = n.t === "Ente" || n.t === "Fornecedor", perto = foco && (n === foco || viz[n.id]);
    if (foco ? !perto : !fixo) return;
    var txt = n.r.length > 26 ? n.r.slice(0, 25) + "…" : n.r, y = n.y + TAMANHO[n.t] + 14;
    ctx.globalAlpha = 1; ctx.lineWidth = 3.5; ctx.strokeStyle = fundo; ctx.strokeText(txt, n.x, y); ctx.fillStyle = tinta; ctx.fillText(txt, n.x, y);
  });
  ctx.globalAlpha = 1;
}
function laco() {
  if (quadros > 0) { passo(); desenhar(); quadros--; requestAnimationFrame(laco); } else { movendo = false; desenhar(); }
}
function agitar(q) { if (calmo) { for (var i = 0; i < q; i++) passo(); desenhar(); return; } quadros = Math.max(quadros, q); if (!movendo) { movendo = true; requestAnimationFrame(laco); } }
function ponto(ev) { var r = tela.getBoundingClientRect(); return { x:ev.clientX - r.left, y:ev.clientY - r.top }; }
function achar(p) {
  var melhor = null, dist = 1e9;
  nos.filter(ativo).forEach(function (n) {
    var d = Math.hypot(n.x - p.x, n.y - p.y); if (d < TAMANHO[n.t] + 8 && d < dist) { dist = d; melhor = n; }
  });
  return melhor;
}
tela.addEventListener("pointerdown", function (ev) {
  var n = achar(ponto(ev)); if (!n) { escolher(null); return; }
  preso = n; escolher(n); try { tela.setPointerCapture(ev.pointerId); } catch (e) {}
});
tela.addEventListener("pointermove", function (ev) {
  var p = ponto(ev);
  if (preso) { preso.x = p.x; preso.y = p.y; agitar(30); return; }
  var n = achar(p); if (n !== sobre) { sobre = n; tela.style.cursor = n ? "pointer" : "grab"; desenhar(); }
});
function soltar() { preso = null; }
tela.addEventListener("pointerup", soltar); tela.addEventListener("pointercancel", soltar);
window.addEventListener("resize", function () { medir(); desenhar(); });
if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", desenhar);
new MutationObserver(desenhar).observe(document.documentElement, { attributes:true, attributeFilter:["data-theme"] });

function dinheiro(v) { return Number(v).toLocaleString("pt-BR", { style:"currency", currency:"BRL" }); }
function campos(n) {
  var p = n.p, l = [];
  function c(rot, v) { if (v !== null && v !== undefined && v !== "") l.push([rot, v]); }
  if (n.t === "Contrato") { c("Valor contratado", dinheiro(p.valor_contratado)); c("Vigência", [p.inicio, p.fim].filter(Boolean).join(" a ")); c("Objeto", p.objeto); c("Aditivo", p.tem_aditivo ? "Sim" : "Não"); c("Processo informado", p.processo_informado ? "Sim" : "Não"); }
  else if (n.t === "Fornecedor") { c("CNPJ", p.cnpj); c("Identidade", p.resolvido ? "Confirmada por documento" : "Sem documento completo"); }
  else if (n.t === "Sancao") { c("Tipo", p.tipo); c("Situação", p.situacao); c("Órgão", p.orgao); c("Publicada em", p.publicada_em); c("Fim da suspensão", p.fim_suspensao); c("Descrição", p.descricao); }
  else if (n.t === "ProcessoLicitatorio") { c("Modalidade", p.modalidade); c("Fase", p.fase); c("Valor estimado", dinheiro(p.valor_estimado)); c("Valor homologado", dinheiro(p.valor_homologado)); c("Data", p.data); }
  else if (n.t === "Ente") { c("Esfera", p.esfera); c("UF", p.uf); }
  else if (n.t === "Evidencia") { c("Trecho", p.trecho); c("Arquivo", p.arquivo); c("Tabela e linha", p.tabela + ", linha " + p.linha); c("Hash do arquivo", p.documento_hash); c("Capturado em", p.capturado_em); }
  return l;
}
function el(tag, cls, txt) { var e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; }
function escolher(n) {
  selecionado = n; desenhar();
  var painel = document.getElementById("painel"); painel.textContent = "";
  if (!n) {
    painel.appendChild(el("p", "tipo", "NADA SELECIONADO"));
    painel.appendChild(el("h2", "", "Clique em um ponto"));
    painel.appendChild(el("p", "", "Cada contrato, sanção e processo leva a uma evidência da fonte. Ative Evidência na legenda para ver todas no grafo."));
    return;
  }
  painel.appendChild(el("p", "tipo", NOME[n.t].toUpperCase()));
  painel.appendChild(el("h2", "", n.r));
  var dl = el("dl");
  campos(n).forEach(function (par) {
    var bloco = el("div"); bloco.appendChild(el("dt", "", par[0]));
    bloco.appendChild(el("dd", par[0] === "Trecho" ? "trecho" : "", String(par[1]))); dl.appendChild(bloco);
  });
  painel.appendChild(dl);
  if (n.t === "Evidencia" && /^https:\/\//.test(n.p.url || "")) {
    var a = el("a", "", "Abrir a fonte"); a.href = n.p.url; a.rel = "noopener"; a.target = "_blank"; painel.appendChild(a);
  }
  var ligs = el("div", "ligado"), vistos = {};
  arestas.forEach(function (e) {
    var outro = e.a === n ? e.b : e.b === n ? e.a : null; if (!outro) return;
    var chave = outro.id + e.rel; if (vistos[chave]) return; vistos[chave] = 1;
    var b = el("button", "", VERBO[e.rel] + ": " + outro.r); b.type = "button";
    b.addEventListener("click", function () { if (!visiveis[outro.t]) ligar(outro.t, true); escolher(outro); }); ligs.appendChild(b);
  });
  if (ligs.children.length) { painel.appendChild(el("p", "tipo", "LIGAÇÕES")); painel.appendChild(ligs); }
}
function ligar(tipo, valor) { visiveis[tipo] = valor; var c = document.getElementById("t-" + tipo); if (c) c.checked = valor; agitar(90); }
var legenda = document.getElementById("legenda"), contagem = {};
nos.forEach(function (n) { contagem[n.t] = (contagem[n.t] || 0) + 1; });
ORDEM.forEach(function (t) {
  if (!contagem[t]) return;
  var r = el("label"), c = document.createElement("input"), p = el("span", "pino");
  c.type = "checkbox"; c.id = "t-" + t; c.checked = visiveis[t]; p.style.background = "var(--" + t + ")";
  c.addEventListener("change", function () { if (selecionado && selecionado.t === t && !c.checked) escolher(null); ligar(t, c.checked); });
  r.appendChild(c); r.appendChild(p); r.appendChild(document.createTextNode(NOME[t] + " " + contagem[t])); legenda.appendChild(r);
});
var numeros = document.getElementById("numeros");
[["pontos", nos.length], ["ligações", arestas.length], ["fornecedores", contagem.Fornecedor || 0], ["contratos", contagem.Contrato || 0], ["sanções", contagem.Sancao || 0]].forEach(function (x) {
  var li = el("li"); li.appendChild(el("b", "", String(x[1]))); li.appendChild(document.createTextNode(" " + x[0])); numeros.appendChild(li);
});
medir(); semear(); for (var i = 0; i < 420; i++) passo(); desenhar();
var inicial = nos.filter(function (n) { return n.t === "Fornecedor"; })
  .sort(function (a, b) { return b.r === a.r ? 0 : arestas.filter(function (e) { return e.a === b && e.rel === "RECEBEU"; }).length - arestas.filter(function (e) { return e.a === a && e.rel === "RECEBEU"; }).length; })[0];
escolher(inicial || null);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(desenhar);
</script>
"""


def main() -> int:
    dados = json.dumps(ler_grafo(), ensure_ascii=False).replace("<", "\\u003c")
    if CPF.search(dados):
        print("ERRO: CPF nos dados; nada foi gravado", file=sys.stderr)
        return 1
    Path(sys.argv[1]).write_text(MOLDE.replace("__DADOS__", dados), encoding="utf8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
