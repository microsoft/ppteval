"""
Codex CLI agent (``codex``).

Invocation
----------
We use ``codex exec --json --skip-git-repo-check`` to drive the agent
non-interactively. Codex streams ndjson events including ``TaskStarted``,
``AgentMessage``, ``ToolCall``, ``TokenCount``, and ``TaskComplete``. We
aggregate tool calls and token usage and parse the final summary.

Reference: ``codex exec --help`` (subject to change).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ppteval.agents.cli.base import CLIAgent, CLIRunResult, CLITelemetry

# OpenAI public price table fallback (USD per 1M tokens). Update as needed.
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "gpt-5.5": {"input": 1.25, "output": 10.0},
    "gpt-5.4": {"input": 1.25, "output": 10.0},
    "o4-mini": {"input": 1.1, "output": 4.4},
}


class CodexCLIAgent(CLIAgent):
    cli_name = "codex-cli"

    def __init__(self, config=None):
        super().__init__(config)
        self.binary = self.config.get("binary") or "codex"
        # Allow YAML to override the price table.
        self.prices: dict[str, dict[str, float]] = (
            self.config.get("prices") or _DEFAULT_PRICES
        )

    def _build_command(self, prompt: str, workspace_dir: Path) -> list[str]:
        cmd: list[str] = [
            self.binary, "exec",
            "--json",
            "--skip-git-repo-check",
        ]
        if self.model:
            cmd += ["-m", str(self.model)]
        cmd += list(self.extra_args)
        # Prompt goes as the trailing positional arg.
        cmd.append(prompt)
        return cmd

    def _parse_telemetry(self, run: CLIRunResult) -> CLITelemetry:
        tel = CLITelemetry(model=self.model)
        tool_counter: Counter[str] = Counter()
        turns: int | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        cached_tokens: int | None = None

        for line in run.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            # Codex wraps payloads under a 'msg' key with a 'type' tag.
            msg = event.get("msg") if isinstance(event.get("msg"), dict) else event
            etype = msg.get("type") or event.get("type")

            if etype in {"tool_call", "ToolCall", "function_call"}:
                name = msg.get("name") or msg.get("tool_name") or "unknown"
                tool_counter[str(name)] += 1
            if etype in {"AgentTurn", "TurnEnd", "turn_end"}:
                turns = (turns or 0) + 1
            if etype in {"TokenCount", "token_count", "usage"}:
                info = msg.get("info") or msg
                if isinstance(info, dict):
                    last = info.get("last_token_usage") or info
                    if isinstance(last, dict):
                        if "input_tokens" in last:
                            input_tokens = (input_tokens or 0) + int(last["input_tokens"])
                        if "output_tokens" in last:
                            output_tokens = (output_tokens or 0) + int(last["output_tokens"])
                        if "cached_input_tokens" in last:
                            cached_tokens = (cached_tokens or 0) + int(last["cached_input_tokens"])
            if etype in {"TaskComplete", "task_complete"}:
                if isinstance(msg.get("num_turns"), int):
                    turns = msg["num_turns"]

        tel.tool_calls_by_name = dict(tool_counter)
        tel.num_tool_calls = sum(tool_counter.values()) or None
        tel.num_turns = turns
        tel.input_tokens = input_tokens
        tel.output_tokens = output_tokens
        tel.cached_tokens = cached_tokens
        tel.cache_read_input_tokens = cached_tokens
        if input_tokens is not None or output_tokens is not None:
            tel.total_tokens = (input_tokens or 0) + (output_tokens or 0)

        # Compute cost from price table if model is known.
        if self.model and tel.total_tokens:
            price = self.prices.get(str(self.model))
            if price:
                cost = (
                    (input_tokens or 0) * price.get("input", 0.0)
                    + (output_tokens or 0) * price.get("output", 0.0)
                ) / 1_000_000.0
                tel.cost_usd = round(cost, 6)
        return tel
