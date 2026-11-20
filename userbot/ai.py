"""Groq calls (chat, vision, speech-to-text)."""
import base64
import os

import httpx

BASE = "https://api.groq.com/openai/v1"


class AIError(Exception):
    pass


class GroqClient:
    def __init__(self, api_key=None):
        self.key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.vision_model = os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        self.whisper = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")

    async def _post(self, path, **kw):
        async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {self.key}"}) as c:
            r = await c.post(BASE + path, **kw)
        if r.status_code >= 400:
            raise AIError(f"AI error {r.status_code}")
        return r.json()

    async def chat(self, system, messages, max_tokens=400, temperature=0.5, model=None):
        data = await self._post("/chat/completions", json={"model": model or self.model, "max_tokens": max_tokens, "temperature": temperature,
                                                           "messages": [{"role": "system", "content": system}, *messages]})
        return data["choices"][0]["message"]["content"].strip()

    async def vision(self, system, history, prompt, image: bytes):
        b64 = base64.b64encode(image).decode()
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]
        return await self.chat(system, [*history, {"role": "user", "content": content}], model=self.vision_model)

    async def transcribe(self, audio: bytes):
        data = await self._post("/audio/transcriptions", data={"model": self.whisper}, files={"file": ("voice.ogg", audio)})
        return data.get("text", "").strip()
