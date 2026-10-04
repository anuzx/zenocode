# Zeno Code

A minimal coding agent that runs in your terminal. Point it at any project folder, tell it what you want, and it reads, searches, edits and runs code for you, asking before anything risky.

It works with any OpenAI-compatible API (OpenRouter, OpenAI, local servers, etc.).

## What it does

- **Agent loop with tools**: `bash`, `read_file`, `write_file` and `str_replace` (exact-match edits).
- **Todo planning**: for multi-step tasks the agent writes a checklist and keeps it updated as it works.
- **Subagents**: exploration questions ("where is X implemented?") are handed to a fresh, read-only agent with its own context window. Only its short report comes back, so your main context stays small.
- **Sandboxed bash**: commands run read-anywhere, write-only-inside-the-project, no network. It uses Seatbelt on macOS and bubblewrap on Linux.
- **Permission rules**: read-only commands (`ls`, `grep`, `git diff`, `pytest`...) run silently, unknown commands ask you first, and dangerous ones (`rm`, `sudo`, `curl`, `git push`...) are always denied. Command substitution (`$(...)`) is always treated as unsafe.
- **Context management**: long tool output is trimmed with the full text saved to a temp file, old tool results shrink to stubs after each turn, and when the window fills up (85%) the history is summarised automatically.
- **Stale-file warnings**: if a file changed on disk since the agent last read it, the agent is told to re-read it before editing.
- **Saved sessions**: every chat is stored as JSONL under `~/.agents/sessions/`, per project.

### Slash commands

| Command     | What it does                                            |
| ----------- | ------------------------------------------------------- |
| `/rewind`   | Jump back to an earlier point in the chat               |
| `/sessions` | Open a past chat                                        |
| `/compact`  | Summarise the history and free up the context window    |

Keys: `Option+Enter` for a newline, `Ctrl+D` to exit.

## Tech stack

| Area                | Used                                                                 |
| ------------------- | -------------------------------------------------------------------- |
| Language            | Python 3.12+                                                         |
| LLM client          | [`openai`](https://pypi.org/project/openai/) SDK (any OpenAI-compatible endpoint) |
| Terminal UI         | [`rich`](https://github.com/Textualize/rich) (panels, markdown, spinners) |
| Input line          | [`prompt_toolkit`](https://github.com/prompt-toolkit/python-prompt-toolkit) (multi-line editing, history) |
| Config              | [`python-dotenv`](https://github.com/theskumar/python-dotenv) + `~/.agents/env` |
| Sandboxing          | `sandbox-exec` (macOS) / `bubblewrap` (Linux)                        |
| Packaging           | `setuptools`, managed with [`uv`](https://docs.astral.sh/uv/)        |


## System Architecture
<img width="3302" height="1130" alt="image" src="https://github.com/user-attachments/assets/610c7466-dc05-457e-a157-158066c97627" />


## Installation

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/) (or `pipx`).

```bash
git clone https://github.com/anuzx/zenocode
cd zenocode
uv tool install .
```

Or install straight from GitHub without cloning:

```bash
uv tool install git+https://github.com/anuzx/zenocode
```

If `zenocode` is not found afterwards, run `uv tool update-shell` and restart your terminal.

### Linux: install bubblewrap (recommended)

Without it the agent still works, but bash runs with `sandbox: none`.

```bash
sudo apt install bubblewrap     # Debian/Ubuntu
sudo dnf install bubblewrap     # Fedora
```

macOS needs nothing extra.

## Configuration

Create `~/.agents/env`:

```bash
mkdir -p ~/.agents
cat > ~/.agents/env <<EOF
BASE_URL=https://openrouter.ai/api/v1
API_KEY=your-api-key
MODEL=openrouter/free
EOF
```

| Variable         | Required | Default            | Meaning                                  |
| ---------------- | -------- | ------------------ | ---------------------------------------- |
| `BASE_URL`       | yes      | none               | Base URL of the OpenAI-compatible API    |
| `API_KEY`        | yes      | none               | Your API key                             |
| `MODEL`          | no       | `openrouter/free`  | Model name to use                        |
| `CONTEXT_WINDOW` | no       | `128000`           | Model context size, in tokens            |

Real environment variables win first, then a `.env` file in the current directory, then `~/.agents/env`. Your model must support tool calling.

## Usage

Go to any project and run:

```bash
cd ~/my-project
zenocode
```

The agent works in the folder you launched it from. It can only write inside that folder, and it asks before running anything that is not on the safe list.

Example prompts:

- `explain how authentication works in this repo`
- `add a --verbose flag to the CLI and update the tests`
- `find and fix the bug causing the failing test in tests/test_parser.py`

## Development

```bash
uv tool install -e . --reinstall   # editable install, code changes apply immediately
uv run -m src.agent                # run without installing
```

## Project layout

```
src/
├── agent.py        # entry point and main loop
├── main.py         # LLM call
├── config.py       # env/config loading
├── tools.py        # bash, read_file, write_file, str_replace
├── subagent.py     # read-only exploration agent
├── commands.py     # /rewind, /sessions, /compact
├── session.py      # JSONL transcripts on disk
├── core/
│   ├── todos.py    # planning checklist
│   ├── context.py  # per-turn reminders (time, branch, todos, stale files)
│   ├── history.py  # trimming and shrinking tool output
│   └── compact.py  # summarising old history
├── safety/
│   ├── permissions.py  # allow / ask / deny rules
│   └── sandbox.py      # OS-level sandbox
└── tui/
    ├── ui.py       # rendering
    └── prompt.py   # input line
```
