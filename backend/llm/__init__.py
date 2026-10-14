"""LLM + embedding provider interfaces.

Two backends exist for each, selected by env var (see .env.example):
  LLM_BACKEND:          "fake" (default) | "gemini"
  EMBEDDING_BACKEND:    "deterministic" (default) | "sentence-transformers"

The defaults need no network, no keys, and are fully deterministic — local
runs, tests, and evals are reproducible. Swap to real providers by setting
env vars; see README "Swapping in real providers".
"""
from .base import EmbeddingProvider, LLMProvider, get_embedding_provider, get_llm_provider

__all__ = ["EmbeddingProvider", "LLMProvider", "get_embedding_provider", "get_llm_provider"]
