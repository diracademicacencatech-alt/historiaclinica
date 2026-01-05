import os
import requests

PPLX_URL = "https://api.perplexity.ai/chat/completions"

def pplx_chat(prompt: str) -> str:
    api_key = os.environ["PPLX_API_KEY"]

    payload = {
        "model": "sonar-pro",
        "messages": [
            {"role": "system", "content": "Responde en español, muy detallado y completo."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 20000,
        "temperature": 0.2,
        # Opcional (solo consistente en sonar/sonar-pro):
        # "language_preference": "Spanish",
    }

    r = requests.post(
        PPLX_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
