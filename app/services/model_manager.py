"""Manages the fine-tuned LLM model loading and inference."""

import json
import os
from pathlib import Path
from typing import AsyncGenerator, List, Optional

import structlog
import torch
from peft import PeftModel
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TextIteratorStreamer,
)

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class ModelManager:
    """Singleton for managing the accounting LLM."""
    
    _instance: Optional["ModelManager"] = None
    _initialized: bool = False
    
    # Model components
    tokenizer: Optional[AutoTokenizer] = None
    base_model: Optional[AutoModelForCausalLM] = None
    model: Optional[PeftModel] = None
    device: str = "cpu"
    using_fine_tuned: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    async def initialize(cls) -> None:
        """Initialize the model."""
        instance = cls()
        
        if instance._initialized:
            return
        
        try:
            logger.info("model_initialization_started", model=settings.base_model)
            
            # Check CUDA availability
            if torch.cuda.is_available():
                instance.device = "cuda"
                logger.info("cuda_available", device_count=torch.cuda.device_count())
            else:
                logger.warning("cuda_not_available", fallback="cpu")
            
            # Load tokenizer
            instance.tokenizer = AutoTokenizer.from_pretrained(
                settings.base_model,
                trust_remote_code=True,
                padding_side="left",
            )
            
            if instance.tokenizer.pad_token is None:
                instance.tokenizer.pad_token = instance.tokenizer.eos_token
            
            # 4-bit quantization config for memory efficiency
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
            
            # Load base model
            instance.base_model = AutoModelForCausalLM.from_pretrained(
                settings.base_model,
                quantization_config=bnb_config,
                device_map="auto" if instance.device == "cuda" else None,
                torch_dtype=torch.float16 if instance.device == "cuda" else torch.float32,
                trust_remote_code=True,
            )
            
            # Load fine-tuned adapter if available
            fine_tuned_path = Path(settings.fine_tuned_model_path)
            if settings.use_fine_tuned and fine_tuned_path.exists():
                logger.info("loading_fine_tuned_adapter", path=str(fine_tuned_path))
                instance.model = PeftModel.from_pretrained(
                    instance.base_model,
                    str(fine_tuned_path),
                )
                instance.using_fine_tuned = True
                logger.info("fine_tuned_adapter_loaded")
            else:
                instance.model = instance.base_model
                instance.using_fine_tuned = False
                logger.warning("using_base_model", reason="fine_tuned_not_found_or_disabled")
            
            instance._initialized = True
            logger.info("model_initialization_completed")
            
        except Exception as e:
            logger.error("model_initialization_failed", error=str(e))
            raise
    
    @classmethod
    def is_ready(cls) -> bool:
        """Check if model is loaded and ready."""
        instance = cls()
        return instance._initialized and instance.model is not None
    
    @classmethod
    async def generate(
        cls,
        prompt: str,
        max_new_tokens: int = 2048,
        temperature: float = 0.1,  # Low temp for accounting accuracy
        top_p: float = 0.9,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate text from the model."""
        instance = cls()
        
        if not instance._initialized:
            raise RuntimeError("Model not initialized")
        
        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # Format for chat
        text = instance.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        
        # Tokenize
        inputs = instance.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=8192,
        )
        
        if instance.device == "cuda":
            inputs = {k: v.cuda() for k, v in inputs.items()}
        
        # Generate
        with torch.no_grad():
            outputs = instance.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=True,
                pad_token_id=instance.tokenizer.pad_token_id,
                eos_token_id=instance.tokenizer.eos_token_id,
            )
        
        # Decode
        generated_text = instance.tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
        )
        
        return generated_text.strip()
    
    @classmethod
    async def generate_structured(
        cls,
        prompt: str,
        output_schema: dict,
        system_prompt: Optional[str] = None,
    ) -> dict:
        """Generate structured JSON output."""
        
        structured_system = f"""{system_prompt or ''}

You must respond with valid JSON only, following this schema:
{json.dumps(output_schema, indent=2)}

Respond with ONLY the JSON object, no markdown formatting, no explanations."""
        
        response = await cls.generate(
            prompt=prompt,
            system_prompt=structured_system,
            max_new_tokens=2048,
            temperature=0.05,  # Very low for structured output
        )
        
        # Extract JSON
        try:
            # Try to find JSON in response
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                json_str = response[start:end+1]
                return json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
        except json.JSONDecodeError as e:
            logger.error("json_decode_failed", response=response, error=str(e))
            raise
    
    @classmethod
    def get_model_info(cls) -> dict:
        """Get current model information."""
        instance = cls()
        return {
            "initialized": instance._initialized,
            "base_model": settings.base_model,
            "using_fine_tuned": instance.using_fine_tuned,
            "device": instance.device,
            "fine_tuned_path": settings.fine_tuned_model_path if instance.using_fine_tuned else None,
        }
