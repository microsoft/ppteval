# PPTEval Benchmark Runner

A comprehensive benchmarking system for evaluating GUI agents on PowerPoint manipulation tasks.

`ppteval` is the supported release path for PowerPoint benchmark runs.

## Table of Contents
- [Quick Start](#quick-start)
- [Running Benchmarks](#running-benchmarks)
- [Resuming Aborted Runs](#resuming-aborted-runs)
- [Re-verification](#re-verification)
- [Configuration](#configuration)
- [Understanding Results](#understanding-results)

## Quick Start

```bash
# Run a quick test with a single task
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --task-ids "3-002" --max-steps 30

# Run full benchmark
python -m ppteval.run_benchmark --agent-config ppteval/configs/claude-4-sonnet.yaml --max-steps 30 --concurrent 4
```

## Running Benchmarks

### Basic Usage

```bash
python -m ppteval.run_benchmark --agent-config <path/to/agent.yaml> [options]
```

### Preset Agent Configs

- **CUA**: `ppteval/configs/cua.yaml`
- **UITARS**: `ppteval/configs/uitars.yaml`, `ppteval/configs/uitars70b.yaml`
- **Claude**: `ppteval/configs/claude-4-sonnet.yaml`, `ppteval/configs/claude-4-opus.yaml`, `ppteval/configs/claude-opus-4-5.yaml`, `ppteval/configs/claude-opus-4-7.yaml`
- **Qwen3-VL**: `ppteval/configs/qwen3vl-8b.yaml`, `ppteval/configs/qwen3vl-32b.yaml`
- **OpenCUA**: `ppteval/configs/opencua-7b.yaml`, `ppteval/configs/opencua-32b.yaml`, `ppteval/configs/opencua-72b.yaml`

Each config declares `agent_type`, `model_name`, API settings, and `display_size`. To add a new model, copy the closest YAML preset and change the config values without editing `run_benchmark.py`. Gemini code remains in-tree as experimental, but it is not part of the release-supported benchmark presets.

### Common Options

| Option | Description | Default |
|--------|-------------|---------|
| `--agent-config` | Agent config YAML to use (required except `--verify-only`) | - |
| `--max-steps` | Maximum steps per task | 10 |
| `--concurrent` | Number of parallel task shards | 1 |
| `--task-ids` | Comma-separated task IDs to run | All tasks |
| `--results-dir` | Custom results directory | Auto-generated timestamp |
| `--timeout-minutes` | Task timeout in minutes | 30 |

### Examples

**Run specific tasks:**
```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --task-ids "3-002,3-003,Obesity-004" --max-steps 30
```

**Run with parallel execution:**
```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/uitars.yaml --concurrent 3 --max-steps 30
```

**Use custom results directory:**
```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --results-dir evaluation_results/cua_run1 --max-steps 30
```

**Overwrite existing results:**
```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --results-dir evaluation_results/cua_run1 --overwrite --max-steps 30
```

## Resuming Aborted Runs

If a benchmark run is interrupted (crash, timeout, Ctrl+C), you can resume it using `--skip-completed`:

```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/uitars.yaml --skip-completed --results-dir results/uitars_evaluate_1758706270 --max-steps 30
```

### How It Works

The `--skip-completed` flag:
1. Scans the results directory, including `shard_*` subdirectories, for existing `result_evaluate.json` files
2. Identifies tasks where **execution completed successfully** (even if the agent failed the task)
3. Skips those tasks and only runs the remaining ones
4. Appends new results to the existing directory

### What Gets Skipped

A task is skipped if:
- `result_evaluate.json` exists
- `execution_status == "success"` (task ran without infrastructure failures)
- `score` is not None (verification completed)

### What Gets Re-run

Tasks are **NOT** skipped if:
- No result file exists (task never started)
- Execution failed with infrastructure error
- Verification crashed (score is None)

### Important Notes

- **DO NOT** use `--overwrite` with `--skip-completed` (they're mutually exclusive)
- Safe to run multiple times - will skip all completed tasks each time
- Works with `--task-ids` to resume specific subsets
- Works with sharded runs; completed tasks are detected under both direct task folders and `shard_*` folders
- Logs show: `"Skipping X already completed tasks"` and `"Remaining tasks to process: Y"`

## Re-verification

If you want to re-verify existing results (e.g., verification failed, or you want to use a different grading method), use `--verify-only`:

```bash
python -m ppteval.run_benchmark --verify-only --results-dir results/uitars_evaluate_1758706270
```

### How It Works

The `--verify-only` flag:
1. Loads tasks from the results directory
2. Re-runs verification on all tasks (or filtered tasks)
3. Updates `result_evaluate.json` and rubric files
4. Does NOT re-run the agent or re-execute tasks

### Use Cases

- **Verification crashed**: Infrastructure issue during grading
- **Updated rubrics**: New grading criteria or bug fixes
- **Selective re-verification**: Use with `--task-ids` to verify specific tasks

### Examples

**Re-verify all tasks:**
```bash
python -m ppteval.run_benchmark --verify-only --results-dir results/cua_evaluate_1758610249
```

**Re-verify specific tasks:**
```bash
python -m ppteval.run_benchmark --verify-only --results-dir results/cua_evaluate_1758610249 --task-ids "3-002,Obesity-004"
```

**Retry only infrastructure failures:**
```bash
python -m ppteval.run_benchmark --verify-only --retry-infrastructure --results-dir results/cua_evaluate_1758610249
```

## Configuration

### Environment Variables

Set these in your `.env` file or environment:

```bash
CLIENT_ID=<your_azure_entra_client_id_for_onedrive>

# For Claude agents
ANTHROPIC_API_KEY=<your_anthropic_key>

# For UITARS agents
UITARS_ENDPOINT_URL=<uitars_endpoint>
UITARS_TOKEN=<uitars_token>

# For Gemini agents
GOOGLE_API_KEY=<your_google_key>
```

### Agent Configuration Files

You can use custom agent config files:

```bash
python -m ppteval.run_benchmark --agent-config configs/cua_custom.yaml
```

### Task Proposal

`ppteval` includes a Claude-based task proposal script for local PowerPoint files:

```bash
python -m ppteval.generate.tasks --files path/to/deck.pptx --agent-config ppteval/configs/claude-4-sonnet.yaml --output-dir proposed_tasks
```

### Task Registry

By default, tasks are loaded from `task_registry/`. You can specify a different path:

```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --task-registry /path/to/custom/registry
```

## Understanding Results

### Directory Structure

After running a benchmark, the results directory contains:

```
results/
└── cua_evaluate_1758610249/
    ├── benchmark_summary.json          # Overall statistics
    ├── benchmark.log                   # Detailed logs
    ├── shard_0/                        # Tasks assigned to shard 0
    │   ├── results_worker_0.jsonl      # Raw results for shard 0
    │   └── 3-002/                      # Individual task results
    │       ├── result_evaluate.json    # Task result and score
    │       ├── result.json             # Task result mirror
    │       ├── actions.json            # Agent action log
    │       ├── scored_rubric.json      # Scored rubric tree
    │       ├── 3-002_363747676.pptx    # Agent's output file
    │       ├── 3-002-363747676.zip     # Slide screenshots
    │       └── screenshots/            # Agent action screenshots
    │           ├── step_000_initial.png
    │           ├── step_001.png
    │           └── ...
    └── shard_1/
        ├── results_worker_1.jsonl
        └── Obesity-004/
            └── ...
```

### Result Files

**`result_evaluate.json`** - Main task result:
```json
{
  "task_id": "3-002",
  "goal": "Task description...",
  "success": true,
  "score": 1.0,
  "reason": "Detailed evaluation...",
  "execution_status": "success",
  "verification_status": "success",
  "agent_steps": 12,
  "evaluation_time_seconds": 45.2
}
```

**`benchmark_summary.json`** - Overall statistics:
```json
{
  "benchmark_info": {
    "start_time": "2025-01-15T10:30:00",
    "end_time": "2025-01-15T14:45:00",
    "total_duration_hours": 4.25
  },
  "overall_stats": {
    "total_tasks": 120,
    "successful_tasks": 85,
    "success_rate": 0.708,
    "avg_score": 0.756,
    "avg_steps": 15.3
  },
  "task_results": [...]
}
```

### Execution Status

- `success` - Task executed successfully (agent may have failed the task)
- `error` - Infrastructure error (sandbox, network, etc.)
- `timeout` - Task exceeded time limit
- `infrastructure_failure` - System-level failure (not agent's fault)

### Verification Status

- `success` - Verification completed successfully
- `failed: rubric evaluation` - Task failed grading criteria
- `failed: missing artifacts` - Required files not found
- `error` - Verification crashed

### Scoring

- `1.0` - Task completed successfully
- `0.0 < score < 1.0` - Partial success (some criteria met)
- `0.0` - Task failed completely
- `null` - Verification did not complete

## Workflow Examples

### Full Benchmark Run

```bash
# 1. Run benchmark with 3 parallel shards
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --concurrent 3 --max-steps 30 --results-dir results/cua_full_run

# 2. Check results
cat results\cua_full_run\benchmark_summary.json
```

### Interrupted Run Recovery

```bash
# 1. Initial run (interrupted at 50/120 tasks)
python -m ppteval.run_benchmark --agent-config ppteval/configs/uitars.yaml --results-dir results/uitars_run1 --max-steps 30
# ... Ctrl+C or crash ...

# 2. Resume from where it left off
python -m ppteval.run_benchmark --agent-config ppteval/configs/uitars.yaml --skip-completed --results-dir results/uitars_run1 --max-steps 30
# Skipping 50 already completed tasks
# Remaining tasks to process: 70
```

### Verification Retry

```bash
# 1. Run benchmark (some verifications failed)
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --results-dir results/cua_run1 --max-steps 30

# 2. Re-verify all tasks
python -m ppteval.run_benchmark --verify-only --results-dir results/cua_run1

# 3. Or re-verify only specific tasks that failed
python -m ppteval.run_benchmark --verify-only --results-dir results/cua_run1 --task-ids "3-003,Obesity-004"
```

### Debugging Workflow

```bash
# 1. Test with a single easy task
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --task-ids "3-002" --max-steps 30

# 2. Test with a few diverse tasks
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --task-ids "3-002,3-003,Obesity-004" --max-steps 30

# 3. Run full benchmark once confident
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --concurrent 4 --max-steps 30
```

## Troubleshooting

### "ERROR: Results directory already exists"

Use `--overwrite` to replace existing results, or choose a different directory.

### Tasks timing out

Increase `--timeout-minutes` (default is 30):
```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --timeout-minutes 60
```

### Agent hitting step limit

Increase `--max-steps` (default is 10):
```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --max-steps 50
```

### Rate limiting (429 errors)

The UITARS agent has built-in retry logic with exponential backoff. If you continue to hit rate limits, reduce `--concurrent` to 1.

### Verification crashes

Use `--verify-only` to retry just the verification step without re-running the agent.

## Advanced Usage

### Display Resolution

The selected agent config is the single source of truth for display resolution. The benchmark uses the same `display_size.width` / `display_size.height` values to configure both the agent and the sandbox. To change resolution, edit the agent YAML passed with `--agent-config`.

### Disable Headless Mode

For debugging, show the browser window:
```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --no-headless --task-ids "3-002"
```

### Custom OneDrive Root

```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --onedrive-root "/CustomFolder"
```

### Step Delay

Add delay between actions (useful for debugging):
```bash
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --step-delay 2.0 --task-ids "3-002"
```

## Support

For issues, questions, or contributions, please refer to the main repository documentation.
