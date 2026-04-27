#!/usr/bin/env python3
"""Download model at Docker build time for faster cold starts."""

import os
import sys

from huggingface_hub import snapshot_download

model_id = "Qwen/Qwen2.5-1.5B-Instruct"
cache_dir = "/app/.cache/huggingface"

os.makedirs(cache_dir, exist_ok=True)

print(f"Downloading {model_id}...", flush=True)
try:
    snapshot_download(
        repo_id=model_id,
        cache_dir=cache_dir,
        resume_download=True,
        local_files_only=False,
    )
    print(f"Model cached at: {cache_dir}", flush=True)
    print("Model download complete!", flush=True)
except Exception as e:
    print(f"Error downloading model: {e}", file=sys.stderr)
    sys.exit(1)
