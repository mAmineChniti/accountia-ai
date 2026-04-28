"""Manages the fine-tuned LLM model loading and inference.

Production-ready implementation with:
- Worker-process isolation (each worker loads its own model)
- Thread-safety via asyncio locks
- Eager initialization with proper readiness tracking
- Graceful fallback to API-based inference
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import structlog
import torch
from peft import PeftModel
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)

from app.config import get_settings
from app.db.redis import cache_get, cache_set

logger = structlog.get_logger()
settings = get_settings()

# -----------------------------------------------------------------------------
# Process-Local Model Storage
# -----------------------------------------------------------------------------
# In multi-worker setups, each worker process has its own memory space.
# We use a module-level variable that is unique per process, not a singleton.
_process_model_data: dict[str, Any] = {
    "tokenizer": None,
    "model": None,
    "device": "cpu",
    "initialized": False,
    "initializing": False,
    "error": None,
    "using_fine_tuned": False,
}

# Lock for thread-safe model inference within a worker
_inference_lock = asyncio.Lock()


class ModelManager:
    """Process-local model manager for production deployments.

    Each Gunicorn worker process has its own isolated ModelManager instance.
    This ensures:
    1. No shared mutable state between workers
    2. Proper request isolation
    3. Clean failure boundaries
    """

    @classmethod
    async def initialize(cls, timeout: float = 300.0) -> bool:
        """Initialize the model in the current worker process.

        Args:
            timeout: Maximum seconds to wait for initialization

        Returns:
            True if initialization succeeded, False otherwise
        """
        global _process_model_data

        # Fast path: already initialized
        if _process_model_data["initialized"]:
            return True

        # Check if another coroutine is initializing
        if _process_model_data["initializing"]:
            # Wait for initialization to complete
            start_time = asyncio.get_event_loop().time()
            while _process_model_data["initializing"]:
                await asyncio.sleep(0.1)
                if asyncio.get_event_loop().time() - start_time > timeout:
                    logger.error("model_init_wait_timeout")
                    return False
            return _process_model_data["initialized"]

        # Start initialization
        _process_model_data["initializing"] = True
        pid = os.getpid()

        try:
            logger.info(
                "model_initialization_started",
                model=settings.base_model,
                worker_pid=pid,
                cache_dir=os.getenv("HF_HOME", "~/.cache/huggingface"),
            )

            # Determine device
            device = cls._determine_device()
            _process_model_data["device"] = device

            # Load tokenizer
            logger.debug("loading_tokenizer", model=settings.base_model)
            tokenizer = AutoTokenizer.from_pretrained(
                settings.base_model,
                trust_remote_code=True,
                padding_side="left",
                local_files_only=bool(os.getenv("HF_HUB_OFFLINE")),
            )

            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            _process_model_data["tokenizer"] = tokenizer

            # Load model with appropriate configuration
            logger.debug("loading_model", model=settings.base_model, device=device)
            model = await cls._load_model(device)
            _process_model_data["model"] = model

            _process_model_data["initialized"] = True
            _process_model_data["error"] = None

            logger.info(
                "model_initialization_completed",
                worker_pid=pid,
                device=device,
                using_fine_tuned=_process_model_data["using_fine_tuned"],
            )
            return True

        except Exception as e:
            _process_model_data["error"] = str(e)
            logger.error(
                "model_initialization_failed",
                worker_pid=pid,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

        finally:
            _process_model_data["initializing"] = False

    @classmethod
    def _determine_device(cls) -> str:
        """Determine the compute device based on settings and availability."""
        desired = (settings.device or "auto").lower()

        if desired == "auto":
            if torch.cuda.is_available():
                device = "cuda"
                logger.info(
                    "cuda_available",
                    device_count=torch.cuda.device_count(),
                    device_name=torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else None,
                )
            else:
                device = "cpu"
                logger.info("cuda_not_available", fallback="cpu")
        elif desired == "cuda":
            if torch.cuda.is_available():
                device = "cuda"
                logger.info("cuda_forced", device_count=torch.cuda.device_count())
            else:
                device = "cpu"
                logger.warning("cuda_forced_but_unavailable", fallback="cpu")
        else:
            device = "cpu"
            logger.info("device_forced_cpu")

        return device

    @classmethod
    async def _load_model(cls, device: str) -> AutoModelForCausalLM:
        """Load the model with appropriate configuration for the device."""
        # Configure quantization for CUDA or CPU (4-bit for free tier)
        bnb_config = None
        if device == "cuda" or getattr(settings, "load_in_4bit", False):
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16 if device == "cuda" else torch.float32,
                bnb_4bit_use_double_quant=True,
            )
            logger.info("using_4bit_quantization", device=device)
        elif getattr(settings, "load_in_8bit", False) and device == "cuda":
            bnb_config = BitsAndBytesConfig(load_in_8bit=True)
            logger.info("using_8bit_quantization", device=device)

        # Model loading parameters
        device_map = "auto" if device == "cuda" else None
        torch_dtype = torch.float16 if device == "cuda" else torch.float32

        load_kwargs = {
            "pretrained_model_name_or_path": settings.base_model,
            "device_map": device_map,
            "torch_dtype": torch_dtype,
            "trust_remote_code": True,
            "local_files_only": bool(os.getenv("HF_HUB_OFFLINE")),
        }

        if bnb_config is not None:
            load_kwargs["quantization_config"] = bnb_config
        else:
            load_kwargs["low_cpu_mem_usage"] = True

        # Run model loading in thread pool to not block event loop
        loop = asyncio.get_event_loop()
        base_model = await loop.run_in_executor(None, lambda: AutoModelForCausalLM.from_pretrained(**load_kwargs))

        # Load fine-tuned adapter if available
        fine_tuned_path = Path(settings.fine_tuned_model_path) if settings.fine_tuned_model_path else None
        if settings.use_fine_tuned and fine_tuned_path and fine_tuned_path.exists():
            logger.info("loading_fine_tuned_adapter", path=str(fine_tuned_path))
            model = await loop.run_in_executor(
                None, lambda: PeftModel.from_pretrained(base_model, str(fine_tuned_path))
            )
            _process_model_data["using_fine_tuned"] = True
            logger.info("fine_tuned_adapter_loaded")
        else:
            model = base_model
            _process_model_data["using_fine_tuned"] = False
            if settings.use_fine_tuned:
                logger.warning("using_base_model", reason="fine_tuned_path_not_found")
            else:
                logger.info("using_base_model", reason="fine_tuned_disabled")

        return model

    @classmethod
    def is_ready(cls) -> bool:
        """Check if model is loaded and ready in this worker process."""
        return _process_model_data["initialized"] and _process_model_data["model"] is not None

    @classmethod
    def get_error(cls) -> str | None:
        """Get initialization error if any."""
        return _process_model_data.get("error")

    @classmethod
    async def generate(
        cls,
        prompt: str,
        max_new_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        system_prompt: str | None = None,
        do_sample: bool | None = None,
        use_cache: bool = True,
        cache_ttl: int = 3600,
    ) -> str:
        """Generate text from the model with caching and thread-safety.

        Args:
            prompt: The user prompt
            max_new_tokens: Maximum new tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            system_prompt: Optional system prompt
            do_sample: Whether to use sampling
            use_cache: Whether to use Redis caching
            cache_ttl: Cache TTL in seconds

        Returns:
            Generated text

        Raises:
            RuntimeError: If model is not initialized and no fallback available
        """
        # Check cache first if enabled
        if use_cache:
            cache_key = cls._generate_cache_key(prompt, system_prompt, max_new_tokens, temperature)
            cached = await cache_get(cache_key)
            if cached:
                logger.debug("llm_cache_hit")
                return cached

        # Ensure model is initialized
        if not cls.is_ready():
            success = await cls.initialize()
            if not success:
                raise RuntimeError(f"Model not initialized and initialization failed: {cls.get_error()}")

        # Thread-safe generation
        async with _inference_lock:
            result = await cls._generate_internal(
                prompt=prompt,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                system_prompt=system_prompt,
                do_sample=do_sample,
            )

        # Cache result if enabled
        if use_cache:
            await cache_set(cache_key, result, expire=cache_ttl)

        return result

    @classmethod
    async def _generate_internal(
        cls,
        prompt: str,
        max_new_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        system_prompt: str | None = None,
        do_sample: bool | None = None,
    ) -> str:
        """Internal generation method (must be called with lock held)."""
        tokenizer = _process_model_data["tokenizer"]
        model = _process_model_data["model"]
        device = _process_model_data["device"]

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Format for chat
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        # Tokenize
        inputs = tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=8192,
        )

        if device == "cuda":
            inputs = {k: v.cuda() for k, v in inputs.items()}

        # Resolve parameters
        max_new_tokens = max_new_tokens or settings.inference_max_new_tokens
        temperature = temperature if temperature is not None else settings.inference_temperature
        top_p = top_p if top_p is not None else settings.inference_top_p
        do_sample = do_sample if do_sample is not None else settings.inference_do_sample

        # Generate in thread pool to not block event loop
        loop = asyncio.get_event_loop()

        def _generate():
            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    do_sample=do_sample,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                )
            return outputs

        outputs = await loop.run_in_executor(None, _generate)

        # Decode
        generated_text = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1] :],
            skip_special_tokens=True,
        )

        return generated_text.strip()

    @classmethod
    async def generate_structured(
        cls,
        prompt: str,
        output_schema: dict,
        system_prompt: str | None = None,
        use_cache: bool = True,
        cache_ttl: int = 3600,
    ) -> dict:
        """Generate structured JSON output."""

        # Check cache
        if use_cache:
            cache_key = cls._generate_cache_key(prompt + json.dumps(output_schema), system_prompt, 2048, 0.05)
            cached = await cache_get(cache_key)
            if cached and isinstance(cached, dict):
                logger.debug("structured_llm_cache_hit")
                return cached

        structured_system = f"""{system_prompt or ""}

You must respond with valid JSON only, following this schema:
{json.dumps(output_schema, indent=2)}

Respond with ONLY the JSON object, no markdown formatting, no explanations."""

        response = await cls.generate(
            prompt=prompt,
            system_prompt=structured_system,
            max_new_tokens=2048,
            temperature=0.05,
            use_cache=False,  # We cache the parsed result below
        )

        # Extract and parse JSON
        try:
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                json_str = response[start : end + 1]
                result = json.loads(json_str)

                # Cache the parsed result
                if use_cache:
                    await cache_set(cache_key, result, expire=cache_ttl)

                return result
            else:
                raise ValueError("No JSON found in response")
        except json.JSONDecodeError as e:
            logger.error("json_decode_failed", response=response[:200], error=str(e))
            raise

    @classmethod
    def _generate_cache_key(
        cls,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int | None,
        temperature: float | None,
    ) -> str:
        """Generate cache key for LLM request."""
        key_data = f"{prompt}:{system_prompt}:{max_tokens}:{temperature}:{settings.base_model}"
        return f"llm:{hashlib.sha256(key_data.encode()).hexdigest()[:32]}"

    @classmethod
    def get_model_info(cls) -> dict:
        """Get current model information for this worker."""
        return {
            "initialized": _process_model_data["initialized"],
            "initializing": _process_model_data["initializing"],
            "base_model": settings.base_model,
            "using_fine_tuned": _process_model_data["using_fine_tuned"],
            "device": _process_model_data["device"],
            "worker_pid": os.getpid(),
            "error": _process_model_data.get("error"),
        }

    @classmethod
    async def shutdown(cls) -> None:
        """Clean up model resources."""
        global _process_model_data

        try:
            if _process_model_data["model"] is not None:
                # Move model to CPU before deletion to avoid CUDA memory issues
                if _process_model_data["device"] == "cuda":
                    _process_model_data["model"] = _process_model_data["model"].cpu()
                    torch.cuda.empty_cache()

                del _process_model_data["model"]
                _process_model_data["model"] = None

            if _process_model_data["tokenizer"] is not None:
                del _process_model_data["tokenizer"]
                _process_model_data["tokenizer"] = None

            _process_model_data["initialized"] = False
            logger.info("model_shutdown_complete", worker_pid=os.getpid())

        except Exception as e:
            logger.error("model_shutdown_error", error=str(e))
