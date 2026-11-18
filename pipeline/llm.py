"""Envoltorio de Ollama con control de presupuesto del challenge.

- think=False: sin razonamiento oculto (gasta tokens y calienta la CPU).
- temperature=0: respuestas reproducibles.
- num_thread: limita núcleos para que la laptop no se recaliente.
- Budget: máximo 15 llamadas y 12.000 tokens generados por pregunta.
"""
import os

MODEL = os.environ.get("GENAI_MODEL", "qwen3:1.7b")
NUM_CTX = int(os.environ.get("GENAI_CTX", 8192))
NUM_THREAD = int(os.environ.get("GENAI_THREADS", max(1, (os.cpu_count() or 4) // 2)))


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, max_calls=15, max_tokens=12000):
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.calls = self.tokens = 0

    def check(self, want_tokens):
        if self.calls + 1 > self.max_calls:
            raise BudgetExceeded("límite de llamadas")
        if self.tokens + want_tokens > self.max_tokens:
            raise BudgetExceeded("límite de tokens")

    def __repr__(self):
        return f"Budget(calls={self.calls}/{self.max_calls}, tokens={self.tokens}/{self.max_tokens})"


def chat(messages, budget: Budget, schema=None, max_tokens=800) -> str:
    import ollama  # import tardío: los tests no necesitan Ollama

    budget.check(max_tokens)
    r = ollama.chat(
        model=MODEL,
        messages=messages,
        format=schema,
        think=False,
        options={"temperature": 0, "num_thread": NUM_THREAD, "num_ctx": NUM_CTX, "num_predict": max_tokens},
    )
    budget.calls += 1
    budget.tokens += int(getattr(r, "eval_count", 0) or 0)
    return r["message"]["content"]
