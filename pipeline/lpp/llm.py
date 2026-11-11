"""OpenAI chat client returning parsed JSON, with responses cached in Postgres."""

import hashlib
import json
import os

import requests
from psycopg.types.json import Jsonb

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIJSON:
    def __init__(self, api_key: str, model: str | None = None, conn=None, session=None):
        self.api_key = api_key
        self.model = model or os.environ.get("LPP_OPENAI_MODEL", "gpt-4o-mini")
        self.conn = conn
        self.session = session or requests.Session()
        self.calls = 0
        self.hits = 0

    def __call__(self, system: str, prompt: str) -> dict:
        key = hashlib.blake2b(f"{self.model}\0{system}\0{prompt}".encode(), digest_size=16).hexdigest()
        if self.conn is not None:
            row = self.conn.execute("SELECT response FROM llm_cache WHERE prompt_hash = %s", (key,)).fetchone()
            if row:
                self.hits += 1
                return row[0]
        resp = self.session.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
            timeout=60)
        resp.raise_for_status()
        self.calls += 1
        result = json.loads(resp.json()["choices"][0]["message"]["content"])
        if self.conn is not None:
            self.conn.execute(
                "INSERT INTO llm_cache (prompt_hash, model, response) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (key, self.model, Jsonb(result)))
        return result


def from_env(conn=None) -> OpenAIJSON | None:
    key = os.environ.get("OPENAI_API_KEY")
    return OpenAIJSON(key, conn=conn) if key else None
