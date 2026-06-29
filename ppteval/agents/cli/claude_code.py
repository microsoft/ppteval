"""
Claude Code CLI agent (``claude``).

Invocation
----------
We use ``--output-format stream-json --verbose`` so the CLI streams ndjson
events that include per-turn assistant messages (with ``tool_use`` blocks),
``tool_result`` messages, and a final ``result`` event carrying
``num_turns``, ``total_cost_usd``, and aggregated ``usage`` tokens.

Reference: https://docs.claude.com/en/docs/claude-code/sdk (subject to change)
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ppteval.agents.cli.base import CLIAgent, CLIRunResult, CLITelemetry


class ClaudeCodeAgent(CLIAgent):
    cli_name = "claude-code"

    # The Claude Code CLI should use its OAuth/keychain session (set via
    # ``claude login``), not the ppteval ``.env`` API key. We therefore
    # scrub Anthropic env vars before spawning:
    #   * ``ANTHROPIC_API_KEY``: forces ``apiKeySource: ANTHROPIC_API_KEY``
    #     and uses whatever (potentially restricted) key is in ``.env``.
    #   * ``ANTHROPIC_BASE_URL``: ppteval's ``.env`` sets this to a full
    #     litellm-style ``/v1/messages`` endpoint; the CLI treats it as a
    #     *base* URL and ends up with a 404 surfaced as a synthetic
    #     "model does not exist" error.
    # Users who explicitly want either var forwarded can list them in the
    # YAML ``env:`` block (which wins over scrubbing).
    default_scrub_env = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")

    def __init__(self, config=None):
        super().__init__(config)
        # Defaults tuned for Claude Code; can be overridden via YAML.
        self.binary = self.config.get("binary") or "claude"
        if not self.config.get("max_turns"):
            self.max_turns = 40

    def _build_command(self, prompt: str, workspace_dir: Path) -> list[str]:
        cmd: list[str] = [
            self.binary,
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]
        # Newer Claude Code versions accept ``--max-turns``; older ones do
        # not. The flag is opt-in via the YAML ``max_turns`` field, AND only
        # appended when explicitly requested via ``send_max_turns: true``.
        if self.max_turns and bool(self.config.get("send_max_turns", False)):
            cmd += ["--max-turns", str(int(self.max_turns))]
        if self.model:
            cmd += ["--model", str(self.model)]
        cmd += list(self.extra_args)
        return cmd

    def _parse_telemetry(self, run: CLIRunResult) -> CLITelemetry:
        tel = CLITelemetry(model=self.model)
        tool_counter: Counter[str] = Counter()
        result_event: dict | None = None

        for line in run.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")

            # Tool use blocks live inside assistant messages.
            if etype == "assistant":
                msg = event.get("message") or {}
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name") or "unknown"
                        tool_counter[name] += 1

            if etype == "result":
                result_event = event

        tel.tool_calls_by_name = dict(tool_counter)
        tel.num_tool_calls = sum(tool_counter.values()) or None

        if result_event:
            tel.num_turns = result_event.get("num_turns")
            cost = result_event.get("total_cost_usd")
            if cost is not None:
                try:
                    tel.cost_usd = float(cost)
                except (TypeError, ValueError):
                    pass
            usage = result_event.get("usage") or {}
            tel.input_tokens = usage.get("input_tokens")
            tel.output_tokens = usage.get("output_tokens")
            cache_creation = usage.get("cache_creation_input_tokens")
            if isinstance(cache_creation, (int, float)):
                tel.cache_creation_input_tokens = int(cache_creation)
            cache_read = usage.get("cache_read_input_tokens")
            if isinstance(cache_read, (int, float)):
                tel.cache_read_input_tokens = int(cache_read)
            cached = (tel.cache_creation_input_tokens or 0) + (tel.cache_read_input_tokens or 0)
            if cached:
                tel.cached_tokens = cached
            if tel.input_tokens is not None or tel.output_tokens is not None:
                tel.total_tokens = (tel.input_tokens or 0) + (tel.output_tokens or 0)
            if not tel.model:
                tel.model = result_event.get("model") or self.model

        return tel
