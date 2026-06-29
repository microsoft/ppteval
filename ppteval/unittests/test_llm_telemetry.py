from types import SimpleNamespace

from ppteval.utils.llm_telemetry import LLMUsageTelemetry


def test_litellm_telemetry_tracks_cache_tokens_separately() -> None:
    response = SimpleNamespace(
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "total_tokens": 110,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 70,
        },
        response_cost=0.123,
    )

    telemetry = LLMUsageTelemetry()
    telemetry.record_litellm_response(response, model="test-model")
    data = telemetry.to_dict()

    assert data["prompt_tokens"] == 100
    assert data["input_tokens"] == 100
    assert data["completion_tokens"] == 10
    assert data["output_tokens"] == 10
    assert data["cache_creation_input_tokens"] == 20
    assert data["cache_read_input_tokens"] == 70
    assert data["cached_tokens"] == 90
    assert data["total_tokens"] == 110
    assert data["cost_usd"] == 0.123


def test_openai_telemetry_reads_nested_cached_tokens() -> None:
    response = {
        "usage": {
            "input_tokens": 100,
            "output_tokens": 10,
            "total_tokens": 110,
            "input_tokens_details": {"cached_tokens": 80},
        },
        "output": [{"type": "computer_call"}],
        "response_cost": 0.456,
    }

    telemetry = LLMUsageTelemetry()
    telemetry.record_openai_response(response, model="test-model")
    data = telemetry.to_dict()

    assert data["input_tokens"] == 100
    assert data["prompt_tokens"] == 100
    assert data["output_tokens"] == 10
    assert data["completion_tokens"] == 10
    assert data["cache_creation_input_tokens"] == 0
    assert data["cache_read_input_tokens"] == 80
    assert data["cached_tokens"] == 80
    assert data["total_tokens"] == 110
    assert data["num_tool_calls"] == 1
    assert data["cost_usd"] == 0.456
