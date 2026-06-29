"""Helpers for accumulating LLM usage metrics across agent calls."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class LLMUsageTelemetry:
    """Task-scoped usage totals collected from LLM provider responses."""

    num_turns: int = 0
    num_tool_calls: int = 0
    input_tokens: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    completion_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    calls: list[dict[str, Any]] = field(default_factory=list)

    def record_litellm_response(self, response: Any, model: str | None = None) -> None:
        """Record token/cost metadata from a LiteLLM completion response."""
        usage_dict = self._coerce_usage_dict(self._value(response, "usage"))
        prompt_tokens = self._first_int_value(usage_dict, "prompt_tokens", "input_tokens")
        completion_tokens = self._int_value(usage_dict, "completion_tokens", "output_tokens")
        cache_creation_input_tokens = self._int_value(usage_dict, "cache_creation_input_tokens")
        cache_read_input_tokens = self._cache_read_tokens(usage_dict)
        cached_tokens = cache_creation_input_tokens + cache_read_input_tokens
        total_tokens = usage_dict.get("total_tokens")
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens
        total_tokens = int(total_tokens or 0)
        cost_usd = self._response_cost(response, model=model)

        self.num_turns += 1
        self.input_tokens += prompt_tokens
        self.prompt_tokens += prompt_tokens
        self.output_tokens += completion_tokens
        self.completion_tokens += completion_tokens
        self.cache_creation_input_tokens += cache_creation_input_tokens
        self.cache_read_input_tokens += cache_read_input_tokens
        self.cached_tokens += cached_tokens
        self.total_tokens += total_tokens
        self.cost_usd += cost_usd
        self.calls.append(
            {
                "model": model,
                "input_tokens": prompt_tokens,
                "prompt_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "completion_tokens": completion_tokens,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
                "cached_tokens": cached_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
                "usage": usage_dict,
            }
        )

    def record_openai_response(self, response: Any, model: str | None = None) -> None:
        """Record usage metadata from an OpenAI Responses API response."""
        usage_dict = self._coerce_usage_dict(self._value(response, "usage"))
        prompt_tokens = self._first_int_value(usage_dict, "prompt_tokens", "input_tokens")
        completion_tokens = self._int_value(
            usage_dict,
            "completion_tokens",
            "output_tokens",
        )
        cache_creation_input_tokens = self._int_value(usage_dict, "cache_creation_input_tokens")
        cache_read_input_tokens = self._cache_read_tokens(usage_dict)
        cached_tokens = cache_creation_input_tokens + cache_read_input_tokens
        total_tokens = usage_dict.get("total_tokens")
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens
        total_tokens = int(total_tokens or 0)
        cost_usd = self._response_cost(response, model=model)
        tool_calls = self._count_openai_tool_calls(response)

        self.num_turns += 1
        self.num_tool_calls += tool_calls
        self.input_tokens += prompt_tokens
        self.prompt_tokens += prompt_tokens
        self.output_tokens += completion_tokens
        self.completion_tokens += completion_tokens
        self.cache_creation_input_tokens += cache_creation_input_tokens
        self.cache_read_input_tokens += cache_read_input_tokens
        self.cached_tokens += cached_tokens
        self.total_tokens += total_tokens
        self.cost_usd += cost_usd
        self.calls.append(
            {
                "model": model,
                "input_tokens": prompt_tokens,
                "prompt_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "completion_tokens": completion_tokens,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
                "cached_tokens": cached_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
                "num_tool_calls": tool_calls,
                "usage": usage_dict,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable telemetry."""
        return asdict(self)

    @staticmethod
    def _value(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    @classmethod
    def _count_openai_tool_calls(cls, response: Any) -> int:
        output = cls._value(response, "output") or []
        count = 0
        for item in output:
            item_type = cls._value(item, "type")
            if item_type in {"computer_call", "function_call", "tool_call"}:
                count += 1
        return count

    @staticmethod
    def _coerce_usage_dict(usage: Any) -> dict[str, Any]:
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return usage
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if hasattr(usage, "dict"):
            return usage.dict()
        try:
            return dict(usage)
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _int_value(usage: dict[str, Any], *keys: str) -> int:
        return sum(int(usage.get(key) or 0) for key in keys)

    @staticmethod
    def _first_int_value(usage: dict[str, Any], *keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if value is not None:
                return int(value or 0)
        return 0

    @classmethod
    def _cache_read_tokens(cls, usage: dict[str, Any]) -> int:
        top_level = cls._int_value(usage, "cache_read_input_tokens")
        if top_level:
            return top_level
        for details_key in ("prompt_tokens_details", "input_tokens_details"):
            details = usage.get(details_key)
            if isinstance(details, dict):
                cached_tokens = details.get("cached_tokens")
                if cached_tokens is not None:
                    return int(cached_tokens or 0)
        return 0

    @staticmethod
    def _response_cost(response: Any, model: str | None = None) -> float:
        hidden_params = (
            response.get("_hidden_params", {}) if isinstance(response, dict) else getattr(response, "_hidden_params", None)
        ) or {}
        if isinstance(hidden_params, dict):
            response_cost = hidden_params.get("response_cost")
            if response_cost is not None:
                return float(response_cost)
        response_cost = response.get("response_cost") if isinstance(response, dict) else getattr(response, "response_cost", None)
        if response_cost is not None:
            return float(response_cost)
        try:
            import litellm

            return float(litellm.completion_cost(completion_response=response, model=model) or 0.0)
        except Exception:  # noqa: BLE001 - usage should still be logged if cost lookup fails.
            return 0.0
