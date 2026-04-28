#!/usr/bin/env python3
"""Download tiny model at Docker build time for faster cold starts.

For free tier (512MB RAM): Use DistilBERT (66M params, ~150MB)
instead of Qwen 1.5B (~3GB).
"""

import os
import sys

from huggingface_hub import snapshot_download

# Tiny DistilBERT for accounting analysis - 66M params, fits in 512MB RAM
# Much smaller than Qwen 1.5B (3GB) or even 0.5B (600MB)
TINY_MODELS = [
    "distilbert-base-uncased",  # 66M params, ~150MB
]

hf_home = "/app/.cache/huggingface"
cache_dir = os.path.join(hf_home, "hub")
os.makedirs(cache_dir, exist_ok=True)
os.environ["HF_HOME"] = hf_home

for model_id in TINY_MODELS:
    print(f"Downloading {model_id} to {cache_dir}...", flush=True)
    try:
        snapshot_download(
            repo_id=model_id,
            cache_dir=cache_dir,
            resume_download=True,
            local_files_only=False,
        )
        print(f"  ✓ {model_id} downloaded", flush=True)
    except Exception as e:
        print(f"  ✗ Error downloading {model_id}: {e}", file=sys.stderr)
        sys.exit(1)

# List what was downloaded
if os.path.exists(cache_dir):
    models = [d for d in os.listdir(cache_dir) if d.startswith("models--")]
    print(f"Cached models: {models}", flush=True)
    total_size = sum(
        os.path.getsize(os.path.join(dirpath, f))
        for dirpath, _, filenames in os.walk(cache_dir)
        for f in filenames
    )
    print(f"Total cache size: {total_size / 1024 / 1024:.1f} MB", flush=True)

print("Model download complete!", flush=True)
