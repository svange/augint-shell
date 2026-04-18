"""Curated model catalog for ai-shell.

Each entry represents an Ollama model tag that has been validated on
RTX 4090-class hardware. The catalog ships with ai-shell and is the
single source of truth for model metadata (role, parameter count,
censored/uncensored, disk footprint, known caveats).

The ``llm models`` CLI command cross-references this catalog against
the active config slots and the models actually pulled into Ollama.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    """Metadata for a single Ollama model tag."""

    tag: str
    role: str  # "chat" | "coding"
    params: str  # e.g. "3B", "8B", "14B", "27B", "30B"
    size_gb: float  # approximate disk footprint in GiB
    uncensored: bool  # True = abliterated / uncensored variant
    description: str  # one-line purpose
    caveats: str = ""  # known issues or limitations


# ---------------------------------------------------------------------------
# Catalog — ordered by role then descending parameter count
# ---------------------------------------------------------------------------
MODEL_CATALOG: tuple[ModelInfo, ...] = (
    # ── Chat models ───────────────────────────────────────────────────────
    ModelInfo(
        tag="qwen3.5:27b",
        role="chat",
        params="27B",
        size_gb=17.0,
        uncensored=False,
        description="Primary chat — best quality, heavy on VRAM",
        caveats="Ollama tool-call bug (ollama #14493)",
    ),
    ModelInfo(
        tag="huihui_ai/qwen3.5-abliterated:27b",
        role="chat",
        params="27B",
        size_gb=17.0,
        uncensored=True,
        description="Uncensored chat — abliterated Qwen3.5 27B",
        caveats="Ollama tool-call bug (ollama #14493)",
    ),
    ModelInfo(
        tag="qwen3.5:14b-instruct",
        role="chat",
        params="14B",
        size_gb=9.0,
        uncensored=False,
        description="Mid-range chat — 4090 sweet spot, fast + capable",
    ),
    ModelInfo(
        tag="huihui_ai/qwen3.5-abliterated:14b",
        role="chat",
        params="14B",
        size_gb=9.0,
        uncensored=True,
        description="Mid-range uncensored chat — abliterated Qwen3.5 14B",
    ),
    ModelInfo(
        tag="dolphin3:8b",
        role="chat",
        params="8B",
        size_gb=5.0,
        uncensored=True,
        description="Fast uncensored — Dolphin fine-tune of Llama 3.1 8B",
    ),
    ModelInfo(
        tag="llama3.1:8b",
        role="chat",
        params="8B",
        size_gb=5.0,
        uncensored=False,
        description="Fast general chat — good for quick tasks",
    ),
    ModelInfo(
        tag="gemma3:12b",
        role="chat",
        params="12B",
        size_gb=8.0,
        uncensored=False,
        description="Google Gemma 3 12B — solid mid-range alternative",
    ),
    ModelInfo(
        tag="llama3.2:latest",
        role="chat",
        params="3B",
        size_gb=2.0,
        uncensored=False,
        description="Ultra-fast 3B — limited capability, near-instant",
    ),
    # ── Coding models ─────────────────────────────────────────────────────
    ModelInfo(
        tag="qwen3-coder:30b-a3b-q4_K_M",
        role="coding",
        params="30B",
        size_gb=19.0,
        uncensored=False,
        description="Primary coding — explicit Ollama tools badge",
        caveats="Reliable native tool_calls below ~5 tools",
    ),
    ModelInfo(
        tag="huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M",
        role="coding",
        params="30B",
        size_gb=19.0,
        uncensored=True,
        description="Uncensored coding — abliterated Qwen3-Coder 30B",
        caveats="Reliable native tool_calls below ~5 tools",
    ),
    ModelInfo(
        tag="qwen2.5-coder:14b-instruct",
        role="coding",
        params="14B",
        size_gb=9.0,
        uncensored=False,
        description="Mid-range coding — previous-gen, proven on 4090",
    ),
    ModelInfo(
        tag="qwen2.5-coder:32b-q4_k_m",
        role="coding",
        params="32B",
        size_gb=19.0,
        uncensored=False,
        description="Large Qwen2.5-Coder — previous-gen, needs full VRAM",
    ),
    ModelInfo(
        tag="devstral:24b",
        role="coding",
        params="24B",
        size_gb=15.0,
        uncensored=False,
        description="Mistral Devstral — strong agentic coding model",
    ),
)

# Fast lookup by tag
_CATALOG_BY_TAG: dict[str, ModelInfo] = {m.tag: m for m in MODEL_CATALOG}


def lookup(tag: str) -> ModelInfo | None:
    """Return catalog entry for *tag*, or ``None`` if untracked."""
    return _CATALOG_BY_TAG.get(tag)


def classify_status(
    tag: str,
    config_tags: set[str],
    pulled_tags: set[str],
) -> str:
    """Classify a model's status relative to config and Ollama state.

    Returns one of:
    - ``"config"``    — in one of the 4 config slots (or extra_models)
    - ``"pulled"``    — downloaded in Ollama but not in config
    - ``"available"`` — in catalog but not pulled
    - ``"untracked"`` — pulled in Ollama but not in catalog
    """
    in_config = tag in config_tags
    in_ollama = tag in pulled_tags
    in_catalog = tag in _CATALOG_BY_TAG

    if in_config:
        return "config"
    if in_ollama and in_catalog:
        return "pulled"
    if in_ollama and not in_catalog:
        return "untracked"
    return "available"
