"""
GitHub Copilot CLI agent (the agentic ``copilot`` binary, ``@github/copilot-cli``).

The Copilot CLI's machine-readable interface and telemetry surface are still
evolving. We invoke it programmatically and capture whatever it emits; cost
is intentionally left null (Copilot is subscription-billed). Tokens and tool
counts are best-effort: when the CLI emits JSON events with usage fields we
parse them; otherwise we report duration + exit code only.

If your installed Copilot CLI version uses different flags, override them
via the YAML config's ``binary`` / ``extra_args`` / ``cmd_template``.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ppteval.agents.cli.base import CLIAgent, CLIRunResult, CLITelemetry


class CopilotCLIAgent(CLIAgent):
    cli_name = "copilot-cli"

    def __init__(self, config=None):
        super().__init__(config)
        self.binary = self.config.get("binary") or "copilot"

    def _build_command(self, prompt: str, workspace_dir: Path) -> list[str]:
        # Default invocation; users with different Copilot CLI versions can
        # override entirely via ``extra_args`` (which we APPEND to) or by
        # subclassing.
        cmd: list[str] = [self.binary]
        # Common flags across recent Copilot CLI versions:
        #   -p / --prompt <text>        : send prompt non-interactively
        #   --allow-all-tools           : skip per-tool confirmations
        #   --no-color                  : cleaner logs
        cmd += ["-p", prompt, "--allow-all-tools", "--no-color"]
        if self.model:
            cmd += ["--model", str(self.model)]
        cmd += list(self.extra_args)
        return cmd

    def _parse_telemetry(self, run: CLIRunResult) -> CLITelemetry:
        tel = CLITelemetry(model=self.model, cost_usd=None)
        tool_counter: Counter[str] = Counter()
        turns: int | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None

        # Best-effort parser: scan stdout for any ndjson events that look
        # like Copilot CLI telemetry. Plain text is just ignored.
        for line in run.stdout.splitlines():
            line = line.strip()
            if not line or line[0] not in "{[":
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            etype = event.get("type") or event.get("event")
            if etype in {"tool_call", "tool_use", "tool"}:
                name = event.get("name") or event.get("tool") or "unknown"
                tool_counter[str(name)] += 1
            if etype in {"turn", "turn_end"}:
                turns = (turns or 0) + 1
            usage = event.get("usage") or {}
            if isinstance(usage, dict):
                if "input_tokens" in usage:
                    input_tokens = (input_tokens or 0) + int(usage["input_tokens"])
                if "output_tokens" in usage:
                    output_tokens = (output_tokens or 0) + int(usage["output_tokens"])

        tel.tool_calls_by_name = dict(tool_counter)
        tel.num_tool_calls = sum(tool_counter.values()) or None
        tel.num_turns = turns
        tel.input_tokens = input_tokens
        tel.output_tokens = output_tokens
        if input_tokens is not None or output_tokens is not None:
            tel.total_tokens = (input_tokens or 0) + (output_tokens or 0)
        # cost_usd intentionally remains None (Copilot subscription).
        return tel
