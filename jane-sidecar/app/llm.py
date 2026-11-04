"""Google GenAI calls. Live turns use Flash, background work uses Pro, embeddings are 768-d."""

import asyncio
import json
from contextvars import ContextVar

from app.config import get_settings

llm_override: ContextVar = ContextVar("g01_llm_override", default=None)


async def complete_json(model: str, system: str, user: str) -> dict:
    override = llm_override.get()
    if override is not None:
        result = override(model, system, user)
        if hasattr(result, "__await__"):
            result = await result
        return result
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("G01_GEMINI_API_KEY is not set")

    def _call() -> dict:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        return json.loads(response.text or "{}")

    return await asyncio.to_thread(_call)


async def embed_text(text: str) -> list[float] | None:
    settings = get_settings()
    if not text.strip() or not settings.gemini_api_key:
        return None

    def _call() -> list[float]:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.embed_content(
            model=settings.gemini_embedding_model,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        values = list(response.embeddings[0].values)
        if len(values) != 768:
            raise RuntimeError(f"expected 768 embedding dimensions, got {len(values)}")
        return values

    return await asyncio.to_thread(_call)
