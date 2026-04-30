"""LLM service with fallback to Groq API."""

import json

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class LLMService:
    """Service for LLM inference with local model + Groq fallback."""

    def __init__(self):
        self.groq_client: httpx.AsyncClient | None = None
        if settings.groq_api_key:
            self.groq_client = httpx.AsyncClient(
                base_url="https://api.groq.com/openai/v1",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(settings.groq_timeout),
            )

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> str:
        """Generate text using local model or Groq fallback."""
        # Local model support removed in this simplified build. Use Groq if configured.
        if self.groq_client:
            return await self._call_groq(prompt, system_prompt, max_tokens, temperature)

        raise RuntimeError("No LLM available (local model removed, Groq not configured)")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_groq(
        self,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Call Groq API."""

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.groq_client.post(
            "/chat/completions",
            json={
                "model": settings.groq_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": 0.9,
            },
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def generate_structured(
        self,
        prompt: str,
        output_schema: dict,
        system_prompt: str | None = None,
    ) -> dict:
        """Generate structured JSON output."""
        # Local model support removed; use Groq for structured generation when available
        if self.groq_client:
            return await self._call_groq_structured(prompt, output_schema, system_prompt)

        raise RuntimeError("No LLM available for structured generation (local model removed)")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_groq_structured(
        self,
        prompt: str,
        output_schema: dict,
        system_prompt: str | None,
    ) -> dict:
        """Call Groq with JSON mode."""

        structured_system = f"""{system_prompt or ""}

You must respond with valid JSON only, following this schema:
{json.dumps(output_schema, indent=2)}

Respond with ONLY the JSON object, no markdown formatting."""

        messages = [
            {"role": "system", "content": structured_system},
            {"role": "user", "content": prompt},
        ]

        response = await self.groq_client.post(
            "/chat/completions",
            json={
                "model": settings.groq_model,
                "messages": messages,
                "max_tokens": 4096,
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        return json.loads(content)

    async def close(self):
        """Close Groq client."""
        if self.groq_client:
            await self.groq_client.aclose()


# Global instance
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get or create LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
