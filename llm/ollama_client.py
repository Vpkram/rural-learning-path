"""Small synchronous Ollama HTTP client with explicit connection and timeout errors."""

from __future__ import annotations

from threading import Lock
from typing import Any, Protocol

import requests


class OllamaError(RuntimeError):
    """Base class for friendly, expected Ollama service failures."""


class OllamaConnectionError(OllamaError):
    """Ollama is not running or cannot be reached."""


class OllamaTimeoutError(OllamaError):
    """An Ollama request exceeded its configured timeout."""


class OllamaModelError(OllamaError):
    """Ollama could not use the requested local model."""


class _Response(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, Any]: ...


class _HttpSession(Protocol):
    def get(self, url: str, *, timeout: float) -> _Response: ...

    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> _Response: ...


class OllamaClient:
    """Use Ollama's local HTTP API; model downloads are never initiated here."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 90.0,
        keep_alive: str | int = "5m",
        session: _HttpSession | None = None,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url must be a non-empty URL.")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number of seconds.")
        if isinstance(keep_alive, bool) or not isinstance(keep_alive, (str, int)):
            raise ValueError("keep_alive must be a duration string or integer seconds.")
        if isinstance(keep_alive, str) and not keep_alive.strip():
            raise ValueError("keep_alive duration must not be empty.")

        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.keep_alive = keep_alive
        self._session = session if session is not None else requests.Session()
        self._request_lock = Lock()

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> _Response:
        try:
            request_method = getattr(self._session, method)
            response = request_method(
                f"{self.base_url}{endpoint}",
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except requests.Timeout as exc:
            raise OllamaTimeoutError(
                f"Ollama did not respond within {self.timeout:g} seconds."
            ) from exc
        except requests.ConnectionError as exc:
            raise OllamaConnectionError(
                "Ollama is not running or is not reachable at "
                f"{self.base_url}. Start Ollama and try again."
            ) from exc
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 404:
                raise OllamaModelError(
                    "Ollama could not find that local model. Check the installed models with `ollama list`."
                ) from exc
            raise OllamaError(f"Ollama returned an HTTP error: {exc}") from exc
        except requests.RequestException as exc:
            raise OllamaError(f"Could not complete the Ollama request: {exc}") from exc

    def is_connected(self) -> bool:
        """Check the local Ollama tags endpoint without loading or downloading a model."""
        self.list_models()
        return True

    def list_models(self) -> tuple[str, ...]:
        """Return names reported by Ollama's local /api/tags endpoint."""
        with self._request_lock:
            response = self._request("get", "/api/tags")
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise OllamaError("Ollama returned invalid model-list data.") from exc
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            raise OllamaError("Ollama model-list response did not contain a models list.")
        names: list[str] = []
        for model in models:
            if isinstance(model, dict) and isinstance(model.get("name"), str) and model["name"].strip():
                names.append(model["name"].strip())
        return tuple(names)

    def generate(
        self,
        model: str,
        prompt: str,
        system: str,
        temperature: float = 0.2,
    ) -> str:
        """Generate one non-streaming response from one explicitly installed model."""
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty installed model name.")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must not be empty.")
        if not isinstance(system, str) or not system.strip():
            raise ValueError("system prompt must not be empty.")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise ValueError("temperature must be a number between 0 and 2.")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2.")

        payload = {
            "model": model.strip(),
            "prompt": prompt,
            "system": system,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": float(temperature)},
        }
        with self._request_lock:
            response = self._request("post", "/api/generate", json=payload)
        try:
            result = response.json()
        except (ValueError, TypeError) as exc:
            raise OllamaError("Ollama returned invalid generation data.") from exc
        generated = result.get("response") if isinstance(result, dict) else None
        if not isinstance(generated, str) or not generated.strip():
            raise OllamaError("Ollama returned an empty response.")
        return generated.strip()
