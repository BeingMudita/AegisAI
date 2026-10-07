"""The model manifest — which model artifacts AegisAI is allowed to load.

See ``backend/model-manifest.yaml`` for the format and how pins are obtained.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings

_SHA256_HEX = 64


def _check_sha256(value: str) -> str:
    digest = value.removeprefix("sha256:").lower()
    if len(digest) != _SHA256_HEX or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(f"not a SHA-256 hex digest: {value!r}")
    return digest


class HuggingFacePin(BaseModel):
    """A Hugging Face repository at an exact commit, with the SHA-256 of each file."""

    name: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")  # a commit, never a branch or tag
    license: str | None = None
    purpose: str | None = None
    files: dict[str, str] = Field(min_length=1)

    @field_validator("files")
    @classmethod
    def _digests(cls, files: dict[str, str]) -> dict[str, str]:
        return {path: _check_sha256(digest) for path, digest in files.items()}


class OllamaPin(BaseModel):
    """An Ollama model by manifest digest (the ID ``ollama list`` shows)."""

    name: str
    digest: str
    weights: str | None = None  # the weights layer digest, for the AI-BOM
    license: str | None = None
    purpose: str | None = None

    @field_validator("digest", "weights")
    @classmethod
    def _digest(cls, value: str | None) -> str | None:
        return None if value is None else _check_sha256(value)


class ModelManifest(BaseModel):
    huggingface: list[HuggingFacePin] = Field(default_factory=list)
    ollama: list[OllamaPin] = Field(default_factory=list)

    def huggingface_pin(self, name: str) -> HuggingFacePin | None:
        return next((p for p in self.huggingface if p.name == name), None)

    def ollama_pin(self, name: str) -> OllamaPin | None:
        wanted = ollama_name(name)
        return next((p for p in self.ollama if ollama_name(p.name) == wanted), None)


def ollama_name(name: str) -> str:
    """Ollama's canonical name: a model without a tag means ``:latest``."""
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


def load_manifest(path: Path) -> ModelManifest:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ModelManifest.model_validate(data)


@lru_cache
def get_manifest() -> ModelManifest:
    """The manifest named by ``MODEL_MANIFEST_PATH`` (empty if the file is missing)."""
    path = get_settings().backend_path(get_settings().model_manifest_path)
    if not path.exists():
        return ModelManifest()
    return load_manifest(path)
