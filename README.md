# <img src="assets/ppteval-logo.png" alt="PPT-Eval Icon" width="420" style="vertical-align: middle;">

A benchmark to evaluate Computer-Use Agents on PowerPoint tasks.

[Website](https://microsoft.github.io/ppteval/) | [Paper PDF](https://openreview.net/pdf?id=GmeK95WQQ4)

## Installation

### Docker
We use docker for sandboxing GUI-based computer-use agents.
Please make sure to install docker before running the benchmark.
CLI-based benchmarking can skip docker installation.

### PPTOnline and OneDrive setup
Please follow the instructions in [SETUP.md](SETUP.md).

### ppteval Python Package

```sh
# With pip
pip install -e .
# Or with uv
uv sync
```

### Env Vars
We recommend creating a .env file in the repo root to provide the needed environment variables.

```env
CLIENT_ID=<See SETUP.md>
RUBRIC_DEFAULT_LLM="anthropic/claude-sonnet-4-20250514" # Model used for VLM calls in verifiers
ANTHROPIC_API_KEY="..."
ANTHROPIC_BASE_URL="..."

# Add any other endpoints/keys needed for benchmarking your specific model/agent
```

## Hydrating PowerPoint data

To populate your OneDrive account with the needed benchmark PPT files, use the follwowing script.

`hydrate_data.py` is a single script that

1. downloads source `.pptx` files from a URL list into a temp folder,
2. uploads each one to OneDrive,
3. opens it in PowerPoint Online (headless Playwright) and downloads both the
   mutated `.pptx` and the slide-image `.zip` into `--output-dir`,
4. deletes the temp folder.

The default temp folder is `data/files/PowerPoint`, which already contains the
canonical `files.txt`:

Step 3 is important because opening the file in PowerPoint Online normalizes the metadata stored in the `.pptx` file.
This reduces spurious differences when benchmark verifiers compare agent-modified files against the original task files.

Note, this step requires playwright to be installed. 
```
python -m playwright install chromium
```

```sh
python hydrate_data.py \
    --urls-file data/files/PowerPoint/files.txt \
    --local-folder _tmp_pptx_downloads \
    --onedrive-folder /PPTEval \
    --output-dir data/files/PowerPoint \
    --allow-data-dir \
    --cleanup-local-folder
```

Override `--output-dir` to write somewhere else; the temp folder
(`--local-folder`) can be a path to any temp folder and is removed at the end when
`--cleanup-local-folder` is passed. `CLIENT_ID` must be set (in the environment
or `.env`) for the OneDrive upload step.


## Benchmarking a GUI-based Computer-Use Agent

```sh
# Run on Selected tasks
python -m ppteval.run_benchmark --agent-config ppteval/configs/cua.yaml --task-ids "3-002" --max-steps 30
# Run on Whole benchmark with 3 threads for concurrent task evaluation.
# We recommend --concurrent to be <= 3 to minimize infra failures/timeouts.
python -m ppteval.run_benchmark --agent-config ppteval/configs/claude-4-sonnet.yaml --concurrent 3 --max-steps 30 
```

Release-supported model presets live under `ppteval/configs/`, including `cua.yaml`, `uitars.yaml`, `uitars70b.yaml`, `claude-4-sonnet.yaml`, `claude-4-opus.yaml`, `claude-opus-4-5.yaml`, `claude-opus-4-7.yaml`, `qwen3vl-8b.yaml`, `qwen3vl-32b.yaml`, `opencua-7b.yaml`, `opencua-32b.yaml`, and `opencua-72b.yaml`.

## Benchmarking CLI-Based Agents

We have also added support for benchmarking models with the Claude Code CLI:

The `claude-code-*.yaml` presets (e.g. `claude-code-opus-4-5.yaml`,
`claude-code-opus-4-7.yaml`) drive the Claude Code CLI (`claude`) inside a
per-task workspace seeded from `claude-workspace/`.

Prerequisites:

1. Install the Claude Code CLI and authenticate:
   ```sh
   claude --version          # confirm installed
   claude login              # OAuth — runs once, credentials persist in keychain
   ```
2. Install the Anthropic `pptx` skill into `claude-workspace/.claude/skills/pptx/`.
   This skill is proprietary to Anthropic and is **not redistributed with this
   repo**. Obtain it from your Anthropic skills source and drop it in so the
   directory looks like:
   ```
   claude-workspace/
     CLAUDE.md
     .claude/
       skills/
         pptx/
           SKILL.md
           LICENSE.txt
           ...
   ```
   Anything under `claude-workspace/.claude/` is git-ignored by `*workspace/*`.
3. Run the benchmark with the desired CLI agent config:
   ```sh
   python -m ppteval.run_benchmark \
     --agent-config ppteval/configs/claude-code-opus-4-5.yaml \
     --concurrent 4
   ```

The CLI agent does NOT use a Docker sandbox or Office Online — it edits
`.pptx` files programmatically inside its workspace. No SSH tunnels or vLLM
endpoints are required.

## Citation

```bibtex
@inproceedings{gandhi2026ppteval,
  title = {PPT-Eval: A Benchmark for Computer-Use Agents on PowerPoint Tasks},
  author = {Gandhi, Apurva and Suryanarayanan, Vishwas and Anwar, Raja Hasnain and Shaik, Firoz and Desai, Shubhang and Nguyen, Thong Q. and Raza, Muhammad Taqi and Chowdhary, Vishal and Neubig, Graham},
  booktitle = {Forty-third International Conference on Machine Learning},
  year = {2026},
  url = {https://openreview.net/pdf?id=GmeK95WQQ4}
}
```

## Contributing

1. Install development dependencies: `pip install -e ".[dev]"`
2. Make your changes
3. Run tests: `pytest`
4. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
