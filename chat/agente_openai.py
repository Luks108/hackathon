"""Cliente para qualquer API compatível com chat completions da OpenAI (DeepSeek, Gemini em /openai, OpenAI, ...).

Quem escolhe este cliente é `provedores.escolher`. Aqui não há nada específico de provedor: base_url, chave, nome do
modelo e preço chegam prontos. Trocar de DeepSeek para Gemini é só trocar esses valores.

O que o laço faz, igual ao `claude -p` do agente principal:
  - sobe UM servidor MCP `transparencia` por pergunta, com o perfil no ambiente dele (o modelo não escolhe o perfil);
  - só oferece ao modelo as tools de agente.PRIMITIVAS; qualquer outro nome pedido pelo modelo é recusado sem executar;
  - usa as mesmas REGRAS e o mesmo `Leitor`, então os eventos (consulta, texto, fonte, fim, erro) e a conferência
    de evidência (hash_confere) são os mesmos de antes. Quem consome não sabe qual provedor respondeu.

A mensagem do assistente é devolvida ao provedor exatamente como veio (inclusive campos extras, como
`reasoning_content` do DeepSeek ou a assinatura de raciocínio do Gemini 3 em `extra_content`).
Não há streaming: o texto chega inteiro, num único evento `texto`, no fim.
"""

import asyncio
import contextlib
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request

MAX_RODADAS = 8     # idas e voltas de tools por pergunta
_FIM = object()


class Indisponivel:
    """Cliente de um modelo sem chave configurada: responde curto e claro, nunca estoura."""

    def __init__(self, modelo: str, motivo: str):
        self.modelo, self.motivo = modelo, motivo

    def perguntar(self, texto, tenants, historico, leitor, limite_s=None):
        yield ("erro", {"motivo": self.motivo})

    def sem_base(self, pergunta: str, sistema: str) -> dict:
        return {"resposta": "", "desfecho": "erro", "erro": self.motivo, "tokens_entrada": None, "tokens_saida": None,
                "custo_usd": None, "total_s": 0.0}


class ErroDoProvedor(Exception):
    """Falha esperada (chave recusada, saldo, limite). A mensagem já é a que vai para quem pergunta."""


class OpenAICompativel:
    def __init__(self, modelo: str, nome: str, base_url: str, chave: str, temperatura=None, preco=None):
        self.modelo, self.nome, self.base_url, self.chave = modelo, nome, base_url.rstrip("/"), chave
        self.temperatura, self.preco = temperatura, preco

    # ---------- HTTP ----------
    def _chamar(self, corpo: dict, limite_s: float) -> dict:
        dados = json.dumps({"model": self.nome, **({"temperature": self.temperatura} if self.temperatura is not None else {}), **corpo}).encode()
        req = urllib.request.Request(self.base_url + "/chat/completions", data=dados, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.chave}", "User-Agent": "fornexia-benchmark"})
        for tentativa in (1, 2):
            try:
                with urllib.request.urlopen(req, timeout=max(limite_s, 5)) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                e.close()
                if e.code in (429, 500, 502, 503) and tentativa == 1:
                    time.sleep(2)
                    continue
                raise ErroDoProvedor(self._explicar(e.code)) from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                causa = getattr(e, "reason", e)      # URLError embrulha o erro de soquete verdadeiro
                if isinstance(causa, ConnectionRefusedError):
                    detalhe = "conexão recusada pelo provedor"
                elif isinstance(causa, TimeoutError):
                    detalhe = "provedor sem resposta (timeout)"
                else:
                    detalhe = "sem conexão com o provedor"
                raise ErroDoProvedor(f"modelo {self.modelo}: {detalhe}") from None
            except ValueError:
                raise ErroDoProvedor(f"modelo {self.modelo}: resposta inválida do provedor") from None

    def _explicar(self, codigo: int) -> str:
        motivo = {400: "pedido recusado pelo provedor", 401: "chave recusada pelo provedor", 403: "chave sem permissão",
                  402: "saldo insuficiente no provedor", 404: "modelo não encontrado no provedor",
                  429: "limite de uso do provedor atingido"}.get(codigo, "provedor com problema")
        return f"modelo {self.modelo}: {motivo} (HTTP {codigo})"

    def _custo(self, uso: dict) -> float | None:
        if not self.preco:
            return None
        entrada = int(uso.get("prompt_tokens") or 0)
        com_cache = int(uso.get("prompt_cache_hit_tokens") or (uso.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        sem_cache, saida = max(entrada - com_cache, 0), int(uso.get("completion_tokens") or 0)
        p_entrada, p_saida, p_cache = self.preco
        return (sem_cache * p_entrada + saida * p_saida + com_cache * p_cache) / 1_000_000

    @staticmethod
    def _somar(leitor_uso: dict, uso: dict, custo: float | None):
        leitor_uso["entrada"] = leitor_uso.get("entrada", 0) + int(uso.get("prompt_tokens") or 0)
        leitor_uso["saida"] = leitor_uso.get("saida", 0) + int(uso.get("completion_tokens") or 0)
        if custo is not None:
            leitor_uso["custo_usd"] = leitor_uso.get("custo_usd", 0.0) + custo
        if "prompt_cache_hit_tokens" in uso or (uso.get("prompt_tokens_details") or {}).get("cached_tokens") is not None:
            lido = int(uso.get("prompt_cache_hit_tokens") or (uso.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
            leitor_uso["cache_lido"] = leitor_uso.get("cache_lido", 0) + lido

    # ---------- sem acesso aos dados ----------
    def sem_base(self, pergunta: str, sistema: str, limite_s: float = 110) -> dict:
        inicio = time.monotonic()
        try:
            r = self._chamar({"messages": [{"role": "system", "content": sistema}, {"role": "user", "content": pergunta}]}, limite_s)
            uso = r.get("usage") or {}
            return {"resposta": ((r["choices"][0]["message"].get("content")) or "").strip(), "desfecho": "ok",
                    "tokens_entrada": int(uso.get("prompt_tokens") or 0), "tokens_saida": int(uso.get("completion_tokens") or 0),
                    "custo_usd": self._custo(uso), "total_s": round(time.monotonic() - inicio, 1)}
        except ErroDoProvedor as e:
            return {"resposta": "", "desfecho": "erro", "erro": str(e), "tokens_entrada": None, "tokens_saida": None,
                    "custo_usd": None, "total_s": round(time.monotonic() - inicio, 1)}

    # ---------- com as tools da base ----------
    def perguntar(self, texto, tenants, historico, leitor, limite_s=None):
        """Gerador de eventos. O laço roda numa thread própria (o cliente MCP é assíncrono) e entrega por fila.
        `limite_s` é o tempo desta tentativa (o fallback reparte o orçamento); sem ele vale AGENTE_LIMITE_S."""
        import agente
        saida: queue.Queue = queue.Queue()
        limite = limite_s or agente.LIMITE_S

        def trabalho():
            try:
                perfil = agente.perfil_dos_entes(tenants)
                asyncio.run(asyncio.wait_for(self._laco(agente, texto, historico or [], perfil, leitor, saida.put, limite), limite))
            except asyncio.TimeoutError:
                saida.put(("erro", {"motivo": "A consulta demorou mais que o esperado."}))
            except ErroDoProvedor as e:
                saida.put(("erro", {"motivo": str(e)}))
            except BaseException as e:  # noqa: BLE001  nada de stack trace para quem pergunta
                while getattr(e, "exceptions", None):     # o cliente MCP embrulha o erro real num grupo
                    e = e.exceptions[0]
                saida.put(("erro", {"motivo": f"falha ao consultar o modelo {self.modelo} ({type(e).__name__})"}))
            finally:
                saida.put(_FIM)

        threading.Thread(target=trabalho, daemon=True).start()
        terminou = False
        while (item := saida.get()) is not _FIM:
            terminou = terminou or item[0] in ("fim", "erro")
            yield item
        if not terminou:
            yield ("erro", {"motivo": "O agente parou sem responder."})

    async def _laco(self, agente, texto, historico, perfil, leitor, emitir, limite=None):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        inicio = time.monotonic()
        servidor = agente.perfis.config_mcp(perfil, python=agente.PYTHON, sessao=getattr(leitor, "request_id", None))["mcpServers"]["transparencia"]
        # O servidor lê o .env sozinho. As chaves de API de provedor NÃO vão para ele.
        ambiente = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
        ambiente.update(servidor["env"])
        agente.NEUTRO.mkdir(parents=True, exist_ok=True)
        parametros = StdioServerParameters(command=servidor["command"], args=servidor["args"], env=ambiente, cwd=str(agente.NEUTRO))
        permitidas = set(agente.PRIMITIVAS)

        pilha = contextlib.AsyncExitStack()
        descarte = open(os.devnull, "w")
        try:
            leitura, escrita = await pilha.enter_async_context(stdio_client(parametros, errlog=descarte))
            sessao = await pilha.enter_async_context(ClientSession(leitura, escrita))
            await self._conversar(agente, sessao, texto, historico, leitor, emitir, permitidas, inicio, limite or agente.LIMITE_S)
        finally:
            await pilha.aclose()
            descarte.close()

    async def _conversar(self, agente, sessao, texto, historico, leitor, emitir, permitidas, inicio, limite):
        await sessao.initialize()
        ferramentas = [{"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {"type": "object", "properties": {}}}}
                       for t in (await sessao.list_tools()).tools if t.name in permitidas]
        if {f["function"]["name"] for f in ferramentas} != permitidas:
            raise RuntimeError("servidor MCP sem as tools esperadas")
        mensagens = [{"role": "system", "content": agente.REGRAS}, {"role": "user", "content": agente.montar_prompt(texto, historico)}]
        leitor.uso = getattr(leitor, "uso", {}) or {}

        for rodada in range(1, MAX_RODADAS + 1):
            restante = limite - (time.monotonic() - inicio)
            t_chamada = time.monotonic()
            try:
                resposta = await asyncio.to_thread(self._chamar, {"messages": mensagens, "tools": ferramentas, "tool_choice": "auto"}, restante)
            except ErroDoProvedor as e:
                agente._log(leitor, "chamada_modelo", "aviso", modelo=self.modelo, rodada=rodada, resultado="falha",
                            duracao_ms=int((time.monotonic() - t_chamada) * 1000), motivo=str(e)[:160],
                            **dict(zip(("causa", "codigo_http"), agente.causa_da_falha(str(e)))))
                raise
            uso = resposta.get("usage") or {}
            self._somar(leitor.uso, uso, self._custo(uso))
            leitor.uso["rodadas"] = rodada
            agente._log(leitor, "chamada_modelo", "debug", modelo=self.modelo, rodada=rodada, resultado="ok",
                        duracao_ms=int((time.monotonic() - t_chamada) * 1000), tokens_entrada=int(uso.get("prompt_tokens") or 0),
                        tokens_saida=int(uso.get("completion_tokens") or 0))
            mensagem = resposta["choices"][0]["message"]
            chamadas = mensagem.get("tool_calls") or []
            for i, c in enumerate(chamadas):
                c.setdefault("id", f"chamada_{len(mensagens)}_{i}")   # alguns provedores não mandam id
                c["id"] = c["id"] or f"chamada_{len(mensagens)}_{i}"
            mensagens.append(mensagem)      # exatamente como veio

            if not chamadas:
                final = (mensagem.get("content") or "").strip()
                if final:
                    for ev in leitor.ler({"type": "stream_event", "event": {"type": "content_block_delta",
                                                                              "delta": {"type": "text_delta", "text": final}}}):
                        emitir(ev)
                for ev in leitor.ler({"type": "result", "duration_ms": int((time.monotonic() - inicio) * 1000)}):
                    emitir(ev)
                return

            for c in chamadas:
                nome = (c.get("function") or {}).get("name", "")
                try:
                    argumentos = json.loads((c.get("function") or {}).get("arguments") or "{}")
                except ValueError:
                    argumentos = None
                if nome not in permitidas or not isinstance(argumentos, dict):
                    leitor.alertas.append(("ferramenta_negada", "aviso", {"ferramenta": str(nome)[:60], "motivo": "fora da lista ou argumentos inválidos"}))
                    mensagens.append({"role": "tool", "tool_call_id": c["id"], "content": "ferramenta não permitida ou argumentos inválidos"})
                    continue
                for ev in leitor.ler({"type": "assistant", "message": {"content": [
                        {"type": "tool_use", "id": c["id"], "name": agente.PREFIXO + nome, "input": argumentos}]}}):
                    emitir(ev)
                resultado = await sessao.call_tool(nome, argumentos)
                blocos = [{"type": "text", "text": b.text} for b in (resultado.content or []) if getattr(b, "text", None) is not None]
                for ev in leitor.ler({"type": "user", "message": {"content": [
                        {"type": "tool_result", "tool_use_id": c["id"], "content": blocos}]}}):
                    emitir(ev)
                mensagens.append({"role": "tool", "tool_call_id": c["id"], "content": "\n".join(b["text"] for b in blocos) or "(sem resultado)"})
        emitir(("erro", {"motivo": "O agente não terminou a consulta."}))
