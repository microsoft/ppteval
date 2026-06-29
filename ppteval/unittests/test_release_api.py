"""Release API smoke tests for ppteval."""

from pathlib import Path

import ppteval
from ppteval.run_benchmark import (
    AGENT_TYPES,
    combine_worker_results,
    create_agent_config,
    get_agent_display_resolution,
    get_agent_type_from_config,
    get_completed_tasks,
    load_previous_results,
    partition_tasks,
)


CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"
RELEASE_VARIANT_CONFIGS = {
    "cua.yaml": ("cua", "computer-use-preview"),
    "uitars.yaml": ("uitars", "uitars-v1"),
    "uitars70b.yaml": ("uitars", "uitars-70b"),
    "claude-4-sonnet.yaml": ("claude", "claude-sonnet-4-20250514"),
    "claude-4-opus.yaml": ("claude", "claude-opus-4-1-20250805"),
    "claude-opus-4-5.yaml": ("claude", "claude-opus-4-5-20251101"),
    "claude-opus-4-7.yaml": ("claude", "claude-opus-4-7"),
    "qwen3vl-8b.yaml": ("qwen3vl", "openai/Qwen/Qwen3-VL-8B-Instruct"),
    "qwen3vl-32b.yaml": ("qwen3vl", "openai/Qwen/Qwen3-VL-32B-Instruct"),
    "opencua-7b.yaml": ("opencua", "custom_openai/opencua-7b"),
    "opencua-32b.yaml": ("opencua", "custom_openai/opencua-32b"),
    "opencua-72b.yaml": ("opencua", "openai/OpenCUA-72B"),
}


def test_top_level_exports_release_agents_and_configs():
    assert ppteval.CUAAgent is not None
    assert ppteval.ClaudeAgent is not None
    assert ppteval.UITARSAgent is not None
    assert ppteval.Qwen3VLAgent is not None
    assert ppteval.OpenCUAAgent is not None
    assert ppteval.DisplaySize is not None
    assert ppteval.ActionSpace is not None
    assert ppteval.CUAActionSpace is not None
    assert ppteval.Qwen3VLActionSpace is not None
    assert ppteval.OpenCUAActionSpace is not None
    assert ppteval.Qwen3VLConfig is not None
    assert ppteval.OpenCUAConfig is not None


def test_release_runner_supports_expected_agent_families():
    assert set(AGENT_TYPES) == {"cua", "uitars", "claude", "qwen3vl", "opencua"}


def test_release_variant_configs_preserve_legacy_parity_models():
    for filename, (agent_type, model_name) in RELEASE_VARIANT_CONFIGS.items():
        config_path = CONFIG_DIR / filename

        assert config_path.exists()
        assert get_agent_type_from_config(config_path) == agent_type
        assert create_agent_config(config_path).model_name == model_name


def test_agent_config_resolution_drives_benchmark_resolution():
    assert get_agent_display_resolution(CONFIG_DIR / "cua.yaml") == (1024, 768)
    assert get_agent_display_resolution(CONFIG_DIR / "opencua-7b.yaml") == (1920, 1080)


def test_partition_tasks_uses_stable_round_robin_shards():
    tasks = [type("TaskStub", (), {"task_id": f"task-{idx}"})() for idx in range(5)]

    shards = partition_tasks(tasks, shard_count=2)

    assert [[task.task_id for task in shard] for shard in shards] == [
        ["task-0", "task-2", "task-4"],
        ["task-1", "task-3"],
    ]


def test_shard_aware_result_loading_and_merging(tmp_path):
    shard_dir = tmp_path / "shard_0"
    completed_task_dir = shard_dir / "task-complete"
    failed_task_dir = shard_dir / "task-infra"
    completed_task_dir.mkdir(parents=True)
    failed_task_dir.mkdir(parents=True)

    (completed_task_dir / "result_evaluate.json").write_text(
        '{"task_id": "task-complete", "success": true, "score": 0.8, '
        '"agent_steps": 3, "execution_status": "success"}',
        encoding="utf-8",
    )
    (failed_task_dir / "result_evaluate.json").write_text(
        '{"task_id": "task-infra", "success": false, "score": null, '
        '"agent_steps": 1, "execution_status": "infrastructure_failure"}',
        encoding="utf-8",
    )
    (shard_dir / "results_worker_0.jsonl").write_text(
        '{"task_id": "task-complete", "success": true, "score": 0.8, '
        '"agent_steps": 3, "execution_status": "success"}\n'
        '{"task_id": "task-infra", "success": false, "score": 0.0, '
        '"agent_steps": 1, "execution_status": "infrastructure_failure"}\n',
        encoding="utf-8",
    )

    assert get_completed_tasks(tmp_path) == {"task-complete"}
    assert load_previous_results(tmp_path)["task-infra"]["execution_status"] == "infrastructure_failure"

    summary = combine_worker_results(tmp_path, start_time=0)
    assert summary["overall_stats"]["total_tasks"] == 2
    assert [result["task_id"] for result in summary["task_results"]] == ["task-complete", "task-infra"]
