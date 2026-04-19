import re
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API
    app_name: str = "Accountia AI Accountant"
    version: str = "1.0.0"
    port: int = 8000
    host: str = "0.0.0.0"
    debug: bool = False
    
    # MongoDB - URI includes platform DB name (e.g., mongodb://localhost:27017/accountia_platform)
    mongo_uri: str = "mongodb://localhost:27017/accountia_platform"
    
    # Redis (for caching and task queue) - from .env REDIS_URL
    redis_url: str = "redis://localhost:6379/0"
    
    # Model Settings - Use base model (fine-tuning requires 8GB+ GPU)
    # For RTX 2050 4GB: use base model or Groq API
    base_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    fine_tuned_model_path: Optional[str] = "./models/accountant-lora"
    use_fine_tuned: bool = False  # Skip training for now - base model works
    
    # Device settings for training/inference
    device: str = "auto"  # auto, cpu, cuda, mps
    load_in_8bit: bool = True  # Use 8-bit quantization to save VRAM
    
    # Groq (fallback API if local model fails)
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_max_tokens: int = 4096
    groq_timeout: int = 120
    
    # Training settings
    training_output_dir: str = "./models/accountant-lora"
    training_epochs: int = 3
    training_batch_size: int = 4
    learning_rate: float = 2e-4
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.1
    
    # Processing
    max_period_days: int = 365  # Max accounting period
    batch_size: int = 100  # Invoices per batch
    
    # Security
    jwt_secret: Optional[str] = None
    api_key: Optional[str] = None
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
    
    def get_platform_db_name(self) -> str:
        """Extract database name from MongoDB URI."""
        # Parse URI like: mongodb://localhost:27017/accountia_platform
        match = re.search(r'/([^/?]+)(?:\?|$)', self.mongo_uri)
        if match:
            return match.group(1)
        # Default if no DB in URI
        return "accountia_platform"


@lru_cache
def get_settings() -> Settings:
    return Settings()
