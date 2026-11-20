"""One prompt through `/v1/chat/completions` of a running model service, with GPU memory (T231).

Usage: python scripts/check_chat_backend.py http://127.0.0.1:8001 "prompt"
Inference only; the service is started with `laris-model serve --backend
laris.model.inference.open_llm:OpenWeightChat` and `LARIS_MODEL_SERVICE__CHAT_MODEL_ID` set.
"""

import json
import sys
import time
import urllib.request


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.load(resp)


def main(argv: list) -> int:
    base, prompt = argv[0].rstrip("/"), argv[1]
    start = time.time()
    out = post(f"{base}/v1/chat/completions", {"messages": [{"role": "user", "content": prompt}]})
    message = out["choices"][0]["message"]
    print(json.dumps({"seconds": round(time.time() - start, 1), "message": message}, indent=1))
    with urllib.request.urlopen(f"{base}/health", timeout=30) as resp:
        print(json.dumps(json.load(resp).get("gpu"), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
