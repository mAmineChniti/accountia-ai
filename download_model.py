#!/usr/bin/env python3
"""Download model at Docker build time for faster cold starts."""

import os
import sys

from huggingface_hub import snapshot_download

model_id = "Qwen/Qwen2.5-0.5B-Instruct"  # 0.5B for free tier (512MB RAM)
# Use standard HF cache directory structure
hf_home = "/app/.cache/huggingface"
cache_dir = os.path.join(hf_home, "hub")

os.makedirs(cache_dir, exist_ok=True)
os.environ["HF_HOME"] = hf_home

print(f"Downloading {model_id} to {cache_dir}...", flush=True)
try:
    snapshot_download(
        repo_id=model_id,
        cache_dir=cache_dir,
        resume_download=True,
        local_files_only=False,
    )
    # List what was downloaded
    if os.path.exists(cache_dir):
        models = [d for d in os.listdir(cache_dir) if d.startswith("models--")]
        print(f"Cached models: {models}", flush=True)
    print("Model download complete!", flush=True)
except Exception as e:
    print(f"Error downloading model: {e}", file=sys.stderr)
    sys.exit(1)
