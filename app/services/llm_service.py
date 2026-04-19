"""LLM service with fallback to Groq API."""

import json
from typing import Optional

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.services.model_manager import ModelManager

logger = structlog.get_logger()
settings = get_settings()


class LLMService:
    """Service for LLM inference with local model + Groq fallback."""
    
    def __init__(self):
        self.groq_client: Optional[httpx.AsyncClient] = None
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
        system_prompt: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> str:
        """Generate text using local model or Groq fallback."""
        
        # Try local model first
        if ModelManager.is_ready():
            try:
                logger.debug("using_local_model")
                return await ModelManager.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                )
            except Exception as e:
                logger.warning("local_model_failed", error=str(e), fallback="groq")
        
        # Fallback to Groq
        if self.groq_client:
            return await self._call_groq(prompt, system_prompt, max_tokens, temperature)
        
        raise RuntimeError("No LLM available (local model not ready, Groq not configured)")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_groq(
        self,
        prompt: str,
        system_prompt: Optional[str],
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
        system_prompt: Optional[str] = None,
    ) -> dict:
        """Generate structured JSON output."""
        
        # Try local model first
        if ModelManager.is_ready():
            try:
                return await ModelManager.generate_structured(
                    prompt=prompt,
                    output_schema=output_schema,
                    system_prompt=system_prompt,
                )
            except Exception as e:
                logger.warning("local_structured_failed", error=str(e))
        
        # Groq fallback with JSON mode
        if self.groq_client:
            return await self._call_groq_structured(prompt, output_schema, system_prompt)
        
        raise RuntimeError("No LLM available for structured generation")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_groq_structured(
        self,
        prompt: str,
        output_schema: dict,
        system_prompt: Optional[str],
    ) -> dict:
        """Call Groq with JSON mode."""
        
        structured_system = f"""{system_prompt or ''}

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
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """Get or create LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
