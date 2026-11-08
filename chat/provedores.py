"""Provedores de modelo: quem atende cada nome de modelo, e se está disponível nesta máquina.

A escolha do cliente fica AQUI, num único ponto (`escolher`). O resto do sistema chama `agente.perguntar(..., modelo=...)`
e enxerga sempre a mesma interface: eventos (consulta, texto, fonte, fim, erro).

Nome do modelo = [provedor:]modelo
    claude-opus-5-5              sem prefixo = Claude, pelo `claude` já logado (como sempre foi)
    deepseek:deepseek-flash      DeepSeek, pela API compatível com a da OpenAI
    gemini:gemini-2.5-flash      Gemini, pelo endpoint /openai do Google (mesmo adaptador, outra base_url e chave)
    openai:gpt-4.1               OpenAI

Acrescentar um provedor compatível com a OpenAI = uma entrada em PROVEDORES + a variável da chave no .env.
Nenhuma chave é obrigatória: sem a variável, o provedor some da lista (`modelos_disponiveis`) e chamá-lo devolve
"modelo X indisponível: chave não configurada", sem stack trace. As chaves vêm do ambiente ou do .env, nunca do código.
"""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# cliente "claude" = `claude -p` (login da conta, ou ANTHROPIC_API_KEY se você quiser faturar pela API).
# cliente "openai" = POST {base_url}/chat/completions com tools. Precos em USD por 1 milhão de tokens:
#   modelo -> (entrada sem cache, saida, entrada com cache). ESTIMATIVA: confira a página de preços do provedor.
PROVEDORES = {
    "claude": {"nome": "Claude", "cliente": "claude", "chave": None},
    "deepseek": {
        "nome": "DeepSeek", "cliente": "openai", "chave": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com", "url_env": "DEEPSEEK_BASE_URL", "temperatura": 0,
        # Página oficial de preços, lida em 08/11/2026: valores do horário de pico (o dobro do fora de pico), por ser o teto.
        "precos": {"deepseek-flash": (0.30, 1.20, 0.006), "deepseek-v4-pro": (1.32, 3.96, 0.044)},
    },
    "gemini": {
        "nome": "Gemini", "cliente": "openai", "chave": "GOOGLE_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "url_env": "GEMINI_BASE_URL", "temperatura": 0,
        "precos": {},   # sem preço configurado: o custo aparece como "—" em vez de inventar um valor
    },
    "openai": {
        "nome": "OpenAI", "cliente": "openai", "chave": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1", "url_env": "OPENAI_BASE_URL", "temperatura": None,
        "precos": {},
    },
}

# Modelos que o benchmark conhece (`--modelos todos`). Os de provedor sem chave entram na rodada só se a chave existir.
MODELOS_BENCHMARK = ["claude-opus-5-5", "claude-sonnet-5-5", "deepseek:deepseek-flash", "deepseek:deepseek-v4-pro"]


def carregar_env() -> None:
    """Lê o .env da raiz. Variável já definida no ambiente do sistema vence, e valor vazio é ignorado
    (uma ANTHROPIC_API_KEY vazia não pode chegar ao `claude`)."""
    arquivo = RAIZ / ".env"
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            k, v = linha.split("=", 1)
            if k.strip() and v.strip():
                os.environ.setdefault(k.strip(), v.strip())


carregar_env()


def separar(modelo: str) -> tuple[str, str]:
    """'deepseek:deepseek-flash' -> ('deepseek', 'deepseek-flash'). Sem prefixo conhecido, é Claude."""
    if ":" in modelo:
        prefixo, resto = modelo.split(":", 1)
        if prefixo.lower() in PROVEDORES and resto:
            return prefixo.lower(), resto
    return "claude", modelo


def nome_do_provedor(modelo: str) -> str:
    return PROVEDORES[separar(modelo)[0]]["nome"]


def chave_de(provedor: str) -> str:
    variavel = PROVEDORES[provedor].get("chave")
    return os.environ.get(variavel, "").strip() if variavel else ""


def indisponivel(modelo: str) -> str | None:
    """None se o modelo pode ser usado agora; senão uma frase curta com o motivo."""
    provedor, _ = separar(modelo)
    variavel = PROVEDORES[provedor].get("chave")
    if variavel and not chave_de(provedor):
        return f"modelo {modelo} indisponível: chave não configurada ({variavel})"
    return None


def modelos_disponiveis(candidatos: list[str] | None = None) -> list[str]:
    return [m for m in (candidatos or MODELOS_BENCHMARK) if indisponivel(m) is None]


def preco_de(modelo: str) -> tuple[float, float, float] | None:
    provedor, nome = separar(modelo)
    tabela = PROVEDORES[provedor].get("precos") or {}
    preco = tabela.get(nome)
    if preco and len(preco) == 2:
        preco = (preco[0], preco[1], preco[0])
    return preco


# Quem assume quando o modelo pedido falha. Troca em AGENTE_FALLBACK_ORDEM (lista separada por vírgula;
# "nenhum" desliga). Modelo de provedor sem chave é pulado, então o padrão nunca exige nada além do que existe na máquina.
ORDEM_FALLBACK_PADRAO = "deepseek:deepseek-flash,claude-sonnet-5-5"


def cadeia(modelo: str) -> list[str]:
    """Modelos a tentar, em ordem: o pedido primeiro, depois a AGENTE_FALLBACK_ORDEM. Sem repetidos e sem os indisponíveis
    (chave ausente). Nunca vazia: se nada estiver disponível devolve [modelo], e o cliente "indisponível" responde como sempre.
    É o único lugar que monta a cadeia; quem a percorre é agente.perguntar."""
    bruto = os.environ.get("AGENTE_FALLBACK_ORDEM", "").strip() or ORDEM_FALLBACK_PADRAO
    alternativos = [] if bruto.lower() == "nenhum" else [m.strip() for m in bruto.split(",") if m.strip()]
    ordem = list(dict.fromkeys([modelo, *alternativos]))
    disponiveis = [m for m in ordem if indisponivel(m) is None]
    return disponiveis or [modelo]


def escolher(modelo: str):
    """O ÚNICO ponto que decide qual cliente atende o modelo. Devolve um objeto com
         .perguntar(texto, tenants, historico, leitor)  -> gerador de eventos
         .sem_base(pergunta, sistema)                    -> dict(resposta, desfecho, tokens_entrada, tokens_saida, custo_usd, total_s)
    Nunca levanta por falta de chave: devolve um cliente que responde "indisponível"."""
    provedor, nome = separar(modelo)
    motivo = indisponivel(modelo)
    if motivo:
        from agente_openai import Indisponivel
        return Indisponivel(modelo, motivo)
    if PROVEDORES[provedor]["cliente"] == "claude":
        import agente
        return agente.ClaudeCLI(nome)
    from agente_openai import OpenAICompativel
    cfg = PROVEDORES[provedor]
    base = os.environ.get(cfg.get("url_env", ""), "").strip() or cfg["base_url"]
    return OpenAICompativel(modelo=modelo, nome=nome, base_url=base, chave=chave_de(provedor),
                            temperatura=cfg.get("temperatura"), preco=preco_de(modelo))
