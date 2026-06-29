# CLAUDE.md — PPTEval per-task workspace

You are running inside a **single-task workspace** for the PowerPoint Computer Use
benchmark. Each invocation handles exactly one task. The harness has prepared
this directory with everything you need.

## Layout

```
.
├── TASK.md                  # the task goal (read this first)
├── OUTPUT_INSTRUCTIONS.md   # exact input/output file paths
├── inputs/<file>.pptx       # the source presentation (read-only)
├── output/                  # write the modified file here
└── .claude/skills/pptx/     # OOXML / python-pptx skill
```

## How to work

1. **Read `TASK.md` and `OUTPUT_INSTRUCTIONS.md` first.** They define the goal
   and the exact path you must write your output to. Follow the output path
   literally — the grader looks for that path and nothing else.
2. **Treat `inputs/` as read-only.** Copy the file before modifying it.
3. **Write your result to `output/<task_id>.<ext>`** exactly as specified.
   If the file is missing or named differently, the task scores 0.
4. **When the output file exists and reflects the requested changes, exit.**
   Do not leave background processes running.

## Tools you have

- The `pptx` skill in `.claude/skills/pptx/` (SKILL.md, plus OOXML
  pack/unpack scripts and python-pptx workflows). Read `SKILL.md` for
  guidance on:
  - text extraction (`python -m markitdown ...`)
  - unpacking/repacking pptx files for raw XML edits
  - common edit patterns (colors, fonts, text replacement, slide
    rearrangement, thumbnails)
- `python` with `python-pptx` and `markitdown` already installed.
- Standard shell utilities.

## Task interpretation tips

- "On slide N" → slide N, **1-indexed** as it appears in PowerPoint.
- "Change the title" → the title placeholder of the slide.
- "Change color to X" → apply to fill / font color as the wording implies.
- "Add a text box / bullet / shape" → create a new element; do not replace
  existing content unless asked.
- Make **only** the changes requested. Do not restructure unrelated slides
  or add commentary.

## Scoring

The grader compares your `output/<task_id>.<ext>` against the original using
a rubric defined per task. Strict success requires `score == 1.0`, so make
sure your edits match the task description precisely.

## Verify-then-retry loop (REQUIRED)

After you produce `output/<task_id>.<ext>`, **do not exit immediately**.
Run a verification pass:

1. **Re-read `TASK.md`** and list every concrete requirement (slide N,
   target object, attribute, exact value, etc.).
2. **Open your output file** with `python-pptx` (or unpack the XML if the
   change is style/layout) and programmatically confirm each requirement
   is satisfied:
   - For text changes: read the run text on the targeted shape and check
     it matches exactly (including capitalisation and punctuation).
   - For color/font/size changes: read the relevant property and assert
     it equals the requested value.
   - For shape/image add/remove/resize: confirm the shape count, type,
     position, or dimensions.
   - For slide reorder/duplicate/delete: confirm slide count and order.
3. **Diff against `inputs/<file>.pptx`** to make sure you did **not**
   change anything outside the task scope.
4. If any check fails, **fix the file and re-verify**. Allow yourself up
   to 3 verification retries before giving up.
5. Only exit once all verification checks pass, or after 3 retries — log
   what failed so the run is debuggable.

Keep the verification script in `sandbox/` or stdout; you don't need to
ship it. The harness only reads `output/<task_id>.<ext>`.

## Common failure modes to guard against

- Writing the output under the wrong filename or extension.
- Modifying `inputs/` in place instead of copying.
- Editing the wrong slide because of 0-indexed vs 1-indexed confusion.
- Replacing a placeholder's entire content when the task only asked to
  add/append.
- Forgetting to save (`prs.save(...)`).
- Leaving a `.pptx` open via `python-pptx` so the file is truncated.
- Skipping the verification step and exiting on the first save.
