"""Command-line interface (`laris`)."""

import os

# Batch shapes vary with sequence length; expandable segments stop the CUDA caching allocator
# from fragmenting (OOM retries at 16 GB while only ~9 GB was allocated). Must precede CUDA init.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
