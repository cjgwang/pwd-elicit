"""
Model inference wrapper.

Loads a HuggingFace causal LM once and exposes a single `generate` method.
The model is intentionally isolated from auth/session concerns — it only
sees the text it should respond to.

If no GPU is available the model falls back to CPU automatically.
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Lazy imports so the module can be imported without torch installed
# (useful for running auth/session tests without a full ML stack).
_pipeline = None
_model_name: Optional[str] = None


def load_model(model_name: str, device: str = "cpu") -> None:
    """
    Load (or reload) the model into the module-level singleton.

    Call this once at startup, not on every request.
    """
    global _pipeline, _model_name

    try:
        from transformers import pipeline as hf_pipeline
    except ImportError as exc:
        raise RuntimeError(
            "transformers is not installed. "
            "Run: pip install transformers torch"
        ) from exc

    logger.info("Loading model '%s' on device '%s'…", model_name, device)
    _pipeline = hf_pipeline(
        "text-generation",
        model=model_name,
        device=0 if device == "cuda" else -1,
    )
    _model_name = model_name
    logger.info("Model '%s' ready.", model_name)


def generate(
    prompt: str,
    history: Optional[List[dict]] = None,
    max_new_tokens: int = 200,
) -> str:
    """
    Generate a response for *prompt*.

    *history* is a list of {"role": ..., "content": ...} dicts used to
    build a simple context string. History is prepended as plain text
    so this works with any causal LM, not just chat-tuned models.

    Raises RuntimeError if the model has not been loaded.
    """
    if _pipeline is None:
        raise RuntimeError("Model is not loaded. Call load_model() first.")

    # Build context string from history
    context = _build_context(history or [], prompt)

    outputs = _pipeline(
        context,
        max_new_tokens=max_new_tokens,
        do_sample=True,
        temperature=0.7,
        top_p=0.9,
        pad_token_id=_pipeline.tokenizer.eos_token_id,
    )

    full_text: str = outputs[0]["generated_text"]
    # Strip the prompt/context prefix so we return only the new content
    response = full_text[len(context):].strip()
    return response if response else "(no response generated)"


def _build_context(history: List[dict], new_prompt: str) -> str:
    """Format history + new prompt into a single string for the model."""
    lines = []
    for msg in history:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    lines.append(f"User: {new_prompt}")
    lines.append("Assistant:")
    return "\n".join(lines)


def is_loaded() -> bool:
    return _pipeline is not None


def current_model() -> Optional[str]:
    return _model_name
