import re
from functools import lru_cache

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

    # Model Settings
    # Leave `base_model` empty to use the built-in TensorFlow tiny analyzer.
    # Set to a model id only if deploying with external HF/Torch-based models and deps installed.
    base_model: str = ""
    fine_tuned_model_path: str | None = "./models/accountant-lora"
    use_fine_tuned: bool = False

    # Device settings for training/inference (only used when external model configured)
    device: str = "cpu"
    load_in_4bit: bool = False
    load_in_8bit: bool = False

    # Groq (fallback API if local model fails)
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_max_tokens: int = 4096
    groq_timeout: int = 120

    # Processing
    max_period_days: int = 365  # Max accounting period
    batch_size: int = 100  # Invoices per batch

    # Inference / model tuning defaults (speed vs quality)
    inference_max_new_tokens: int = 512
    inference_do_sample: bool = False
    inference_temperature: float = 0.0
    inference_top_p: float = 0.9

    # Runtime tuning / deploy-time hints (optional)
    enable_tiny_analyzer: bool = False
    gunicorn_workers: int = 1
    log_level: str = "info"
    omp_num_threads: int = 1
    mkl_num_threads: int = 1
    tokenizers_parallelism: bool = False
    # Request/response logging (debugging)
    enable_request_logging: bool = False
    request_log_max_body_chars: int = 2000

    # Security
    jwt_secret: str | None = None
    api_key: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def get_platform_db_name(self) -> str:
        """Extract database name from MongoDB URI."""
        # Parse URI like: mongodb://localhost:27017/accountia_platform
        match = re.search(r"/([^/?]+)(?:\?|$)", self.mongo_uri)
        if match:
            return match.group(1)
        # Default if no DB in URI
        return "accountia_platform"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Normalize common URL/secret fields that may be quoted in .env
    for attr in (
        "mongo_uri",
        "redis_url",
        "groq_api_key",
        "api_key",
        "jwt_secret",
        "fine_tuned_model_path",
        "base_model",
    ):
        val = getattr(s, attr, None)
        if isinstance(val, str) and val:
            # strip whitespace and any surrounding single/double quotes
            cleaned = val.strip().strip('"').strip("'")
            setattr(s, attr, cleaned)

    return s
