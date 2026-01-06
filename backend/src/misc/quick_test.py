import os
import sys 
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import requests
from backend.src.llm.config_loader import load_github_models_config

def main() -> None:
    """Minimal smoke test calling GitHub Models via /inference/chat/completions."""
    cfg = load_github_models_config()
    base_url = cfg["base_url"].rstrip("/")
    api_key  = cfg["api_key"]
    model_id = cfg["model"]

    common_headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 1) Catalog check
    r = requests.get(f"{base_url}/catalog/models", headers=common_headers, timeout=60)
    r.raise_for_status()
    catalog = r.json()
    print("Catalog OK. Sample:", (catalog[0].get("id", catalog[0]) if isinstance(catalog, list) and catalog else catalog))

    # 2) Minimal chat completion
    headers = dict(common_headers, **{"Content-Type": "application/json"})
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "You are a helpful coding assistant."},
            {"role": "user", "content": "Say hello from a script."}
        ],
        "max_tokens": 64,
    }
    resp = requests.post(f"{base_url}/inference/chat/completions", headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    print("Reply:", data["choices"][0]["message"]["content"])

if __name__ == "__main__":
    main()