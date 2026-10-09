"""Choose one installed Ollama model without downloading anything."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

DEFAULT_MODEL = "llama3:latest"
FALLBACK_MODELS = ("llama3.2:3b", "qwen2.5:7b", "qwen2.5:3b")
INSTALL_INSTRUCTIONS = "No Ollama model is installed. Install one explicitly with: ollama pull llama3"


class NoModelAvailableError(RuntimeError):
    """Raised when there is no installed model usable by the tutor."""

    def __init__(self) -> None:
        super().__init__(INSTALL_INSTRUCTIONS)


@dataclass(frozen=True)
class ModelSelection:
    active_model: str
    available_models: tuple[str, ...]
    candidates: tuple[str, ...]


def _canonical_model_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        return ""
    return normalized if ":" in normalized else f"{normalized}:latest"


class ModelSelector:
    """Select the preferred installed model, with the configured fallback order."""

    def __init__(
        self,
        default_model: str = DEFAULT_MODEL,
        fallback_models: Iterable[str] = FALLBACK_MODELS,
    ) -> None:
        self.default_model = _canonical_model_name(default_model)
        self.fallback_models = tuple(_canonical_model_name(model) for model in fallback_models)
        if not self.default_model or any(not model for model in self.fallback_models):
            raise ValueError("Default and fallback model names must not be empty.")

    def select(
        self,
        installed_models: Iterable[str],
        preferred_model: str | None = None,
    ) -> ModelSelection:
        """Return an available active model and installed fallback candidates."""
        installed: dict[str, str] = {}
        for model in installed_models:
            if not isinstance(model, str) or not model.strip():
                continue
            canonical = _canonical_model_name(model)
            installed.setdefault(canonical.casefold(), canonical)
        if not installed:
            raise NoModelAvailableError()

        preferred = _canonical_model_name(preferred_model) if preferred_model else ""
        ranked = [preferred, self.default_model, *self.fallback_models]
        ordered_keys: list[str] = []
        for model in ranked:
            key = model.casefold()
            if key in installed and key not in ordered_keys:
                ordered_keys.append(key)

        # If Ollama has a different installed model, keep it selectable as a last resort.
        for key in installed:
            if key not in ordered_keys:
                ordered_keys.append(key)

        candidates = tuple(installed[key] for key in ordered_keys)
        return ModelSelection(
            active_model=candidates[0],
            available_models=tuple(installed.values()),
            candidates=candidates,
        )
