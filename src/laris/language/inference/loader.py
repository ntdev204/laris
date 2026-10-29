"""Loads a trained language encoder checkpoint together with its tokenizer."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from laris.language.encoder.transformer import (
    LanguageEncoderConfig,
    LargeLanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.language.training.checkpoint import MODEL_FILE, file_sha256, read_manifest


@dataclass
class LoadedEncoder:
    model: Any
    tokenizer: Any
    config: LanguageEncoderConfig
    device: str
    manifest: Dict[str, Any]
    checkpoint: Path

    @property
    def seq_len(self) -> int:
        return int(self.config.max_sequence_length)


def load_tokenizer(model_path: Path) -> Any:
    try:
        import sentencepiece as spm
    except ImportError as exc:
        raise RuntimeError("sentencepiece is required: pip install -e '.[training]'") from exc
    return spm.SentencePieceProcessor(model_file=str(model_path))


def load_encoder(
    checkpoint: Path,
    tokenizer_model: Optional[Path] = None,
    device: Optional[str] = None,
    tokenizer: Any = None,
) -> LoadedEncoder:
    """Rebuilds the model from the checkpoint manifest, verifying weights and tokenizer.

    Refuses checkpoints whose weights digest does not match, and tokenizers whose digest differs
    from the one recorded at training time.
    """
    import torch

    checkpoint = Path(checkpoint)
    manifest = read_manifest(checkpoint)
    if file_sha256(checkpoint / MODEL_FILE) != manifest["model_sha256"]:
        raise ValueError(f"Checkpoint {checkpoint} is corrupt: model.pt digest mismatch")

    provenance = manifest["provenance"]
    recorded = provenance.get("tokenizer_sha256")
    if tokenizer_model is not None:
        if recorded and file_sha256(Path(tokenizer_model)) != recorded:
            raise ValueError("Tokenizer does not match the one used to train this checkpoint")
        tokenizer = load_tokenizer(Path(tokenizer_model))
    if tokenizer is None:
        raise ValueError("A tokenizer (--tokenizer-model) is required")

    config_cls = (
        LargeLanguageEncoderConfig
        if provenance.get("model_size") == "large"
        else LanguageEncoderConfig
    )
    config = config_cls(**provenance["model_config"])
    target = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model = PyTorchTransformerEncoder(config)
    model.load_state_dict(torch.load(checkpoint / MODEL_FILE, map_location="cpu"))
    model.to(target).eval()
    return LoadedEncoder(model, tokenizer, config, target, manifest, checkpoint)
