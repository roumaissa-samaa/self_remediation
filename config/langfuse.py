import os
from dotenv import load_dotenv


def _count_tokens(text: str) -> int:
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, len(text) // 4)

load_dotenv(override=True)

os.environ["LANGFUSE_PUBLIC_KEY"] = os.getenv("LANGFUSE_PUBLIC_KEY", "")
os.environ["LANGFUSE_SECRET_KEY"] = os.getenv("LANGFUSE_SECRET_KEY", "")
os.environ["LANGFUSE_HOST"]       = os.getenv("LANGFUSE_URL", "")

_client = None

def get_client():
    global _client
    if _client is None:
        from langfuse import Langfuse
        _client = Langfuse()
    return _client

def get_langfuse_handler():
    try:
        from langfuse.callback import CallbackHandler
        pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sk = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_URL", "")
        if pk and sk and host:
            return CallbackHandler(public_key=pk, secret_key=sk, host=host)
    except Exception as e:
        print(f"[WARN] Langfuse handler non disponible : {e}")
    return None

def trace_llm(name: str, input_text: str, output_text: str, model: str,
            session_id: str = None):
    try:
        client = get_client()
        trace  = client.trace(
            name=name,
            session_id=session_id 
        )
        trace.generation(
            name=name,
            model=model,
            input=[{"role": "user", "content": input_text}],
            output=output_text,
            usage={
                "input":  _count_tokens(input_text),
                "output": _count_tokens(output_text),
                "unit":   "TOKENS"
            }
        )
        client.flush()
        print(f"Langfuse trace enregistre : {name}")
    except Exception as e:
        print(f"Langfuse trace erreur : {e}")