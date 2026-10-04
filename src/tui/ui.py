"""Terminal presentation layer.

Knows nothing about LLMs, providers or tools - it only receives plain strings
and dicts and decides how they look.
"""

import json
from contextlib import contextmanager

from rich.console import Console, Group
from rich.json import JSON
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from src.core.todos import MARKS
from src.tui import prompt

ACCENT = "#7aa2f7"
USER = "#9ece6a"
TOOL = "#e0af68"
MUTED = "#565f89"

MAX_TOOL_OUTPUT_LINES = 12
MAX_WRITE_LINES = 20  # lines of a written file or edit shown before "… N more"

TODO_STYLES = {
    "done": f"{MUTED} strike",
    "in_progress": f"bold {ACCENT}",
    "pending": MUTED,
}


class UI:
    def __init__(self):
        self.console = Console()
        self._totals = {}

    # ---------------------------------------------------------------- input

    def banner(self, sandbox_name="none"):
        self.console.print()
        self.console.print(
            Padding(
                Panel(
                    Text(
                        f"sandbox: {sandbox_name}  ·  opt-enter for a newline  ·  ctrl-d to exit",
                        style=MUTED,
                    ),
                    title=Text("zenocode", style=f"bold {ACCENT}"),
                    title_align="left",
                    border_style=MUTED,
                    padding=(0, 1),
                ),
                (0, 2, 0, 2),
            )
        )

    def clear(self):
        self.console.clear()

    def resumed(self, messages, label="resumed"):
        turns = sum(1 for m in messages if m["role"] == "user")
        self.console.print(
            Padding(
                Text(
                    f"{label} · {len(messages)} messages · {turns} turns", style=MUTED
                ),
                (0, 0, 0, 2),
            )
        )

    def replay(self, messages):
        """Redraw a loaded transcript so the screen matches the history."""
        results = {
            m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"
        }
        for message in messages:
            if message["role"] == "user":
                self.user(message["content"])
            elif message["role"] == "assistant":
                if message.get("content"):
                    self.agent(message["content"])
                for call in message.get("tool_calls") or []:
                    self.tool(
                        call["function"]["name"],
                        json.loads(call["function"]["arguments"]),
                        results.get(call["id"], ""),
                    )

    def approve(self, reason):
        self.console.print(Padding(Text(reason, style=f"bold {TOOL}"), (1, 0, 0, 2)))
        try:
            answer = prompt.read("  allow? (y/n)> ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.lower().startswith("y")

    def note(self, text):
        self.console.print(Padding(Text(text, style=MUTED), (1, 0, 0, 2)))

    def pick(self, title, rows):
        """Numbered list; returns the chosen index or None."""
        self.console.print(Padding(Text(title, style=f"bold {ACCENT}"), (1, 0, 0, 2)))
        for i, row in enumerate(rows):
            self.console.print(
                Padding(Text(f"{i:>3}  {row}", style=MUTED), (0, 0, 0, 2))
            )
        try:
            answer = prompt.read("\n  number> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return int(answer) if answer.isdigit() and int(answer) < len(rows) else None

    def ask(self):
        self.console.print()
        try:
            return prompt.read("> ").strip()
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return ""

    def start(self):
        """A thin accent rule shown once, right when zenocode launches -
        the "you are here, the app just started" marker. Not shown again
        per turn, so it doesn't compete with ui.turn()-style noise in a
        long session."""
        self.console.print(Rule(style=ACCENT))

    # --------------------------------------------------------------- output

    def user(self, text):
        self.console.print(
            Padding(Text(text.strip(), style=f"bold {USER}"), (1, 0, 0, 2))
        )

    def agent(self, text):
        self.console.print(
            Padding(
                Group(
                    Text("agent", style=f"bold {ACCENT}"),
                    Padding(Markdown(text.strip()), (1, 0, 0, 0)),
                ),
                (1, 2, 0, 2),
            )
        )

    def tool(self, name, args, result, nested=False):
        if name == "write_todos" and args.get("todos"):
            return self.todos(args["todos"])

        if name == "write_file" and "content" in args:
            header, body = self._write_view(args, result)
        elif name == "str_replace" and "old_str" in args:
            header, body = self._edit_view(args, result)
        else:
            header = Text.assemble(
                (f"{name} ", f"bold {TOOL}"),
                (self._format_args(args), MUTED),
            )
            body = self._format_result(result)

        self.console.print(
            Padding(
                Panel(
                    Group(header, Rule(style=MUTED), body),
                    border_style=MUTED,
                    padding=(0, 1),
                ),
                (1, 2, 0, 6 if nested else 2),
            )
        )

    def subagent(self, description):
        """Shown to you, never to the main agent - it only gets the report."""
        self.console.print(
            Padding(
                Panel(
                    Text(description.strip(), style=MUTED),
                    title=Text("subagent · own context", style=f"bold {ACCENT}"),
                    title_align="left",
                    border_style=ACCENT,
                    padding=(0, 1),
                ),
                (1, 2, 0, 4),
            )
        )

    def injection(self, text):
        self.console.print(
            Padding(
                Panel(
                    Text(text.strip(), style=MUTED),
                    title=Text("late injection", style=f"italic {MUTED}"),
                    title_align="left",
                    border_style=MUTED,
                    padding=(0, 1),
                ),
                (1, 2, 0, 2),
            )
        )

    def debug(self, data):
        self.console.print(
            Padding(
                Panel(
                    JSON.from_data(data),
                    title=Text("raw response", style=f"italic {MUTED}"),
                    title_align="left",
                    border_style=TOOL,
                    padding=(0, 1),
                ),
                (1, 2, 0, 2),
            )
        )

    @contextmanager
    def working(self, label="thinking"):
        with self.console.status(
            Text(label, style=MUTED), spinner="dots", spinner_style=ACCENT
        ):
            yield

    def phase(self, tool_name, args):
        """A spinner label that says what is actually happening, instead of
        going silent (or showing a flat 'thinking') while a tool runs."""
        if tool_name == "bash":
            command = args.get("command", "")
            shown = command[:60] + ("…" if len(command) > 60 else "")
            return f"running: {shown}"
        if tool_name == "write_file":
            return f"writing {args.get('path', '')}"
        if tool_name == "str_replace":
            return f"editing {args.get('path', '')}"
        if tool_name == "read_file":
            return f"reading {args.get('path', '')}"
        if tool_name == "task":
            return "delegating to subagent"
        if tool_name == "write_todos":
            return "updating plan"
        return f"running {tool_name}"

    # ---------------------------------------------------------------- usage

    def usage(self, stats):
        for key, value in stats.items():
            self._totals[key] = self._totals.get(key, 0) + (value or 0)

        parts = " · ".join(
            f"{value:,} {key.replace('_tokens', '')}"
            for key, value in stats.items()
            if value
        )
        self.console.print(Padding(Text(parts, style=MUTED), (1, 0, 0, 2)))

    def summary(self):
        if not self._totals:
            return

        table = Table.grid(padding=(0, 2))
        table.add_column(style=MUTED)
        table.add_column(style=f"bold {ACCENT}", justify="right")
        for key, value in self._totals.items():
            table.add_row(key.replace("_", " "), f"{value:,}")

        self.console.print(Padding(table, (1, 2)))
        self.console.print(Rule(style=MUTED))
        self.console.print()

    def compacted(self, before, messages):
        summary = next(
            (m["content"] for m in messages if "<summary>" in (m.get("content") or "")),
            "",
        )
        self.console.print(
            Padding(
                Panel(
                    Markdown(
                        summary.replace("<summary>", "").replace("</summary>", "")
                    ),
                    title=Text(
                        f"compacted · {before} → {len(messages)} messages",
                        style=f"bold {TOOL}",
                    ),
                    title_align="left",
                    border_style=TOOL,
                    padding=(0, 1),
                ),
                (1, 2, 0, 2),
            )
        )

    def todos(self, todos):
        """The plan, as a checklist. The raw tool output is never worth showing."""
        done = sum(1 for t in todos if t["status"] == "done")

        rows = Table.grid(padding=(0, 1))
        rows.add_column(no_wrap=True)
        rows.add_column(overflow="fold")
        for todo in todos:
            status = todo["status"]
            style = TODO_STYLES[status]
            rows.add_row(
                Text(MARKS[status], style=style),
                Text(todo["content"], style=style),
            )

        self.console.print(
            Padding(
                Panel(
                    rows,
                    title=Text(f"todos {done}/{len(todos)}", style=f"bold {TOOL}"),
                    title_align="left",
                    border_style=MUTED,
                    padding=(0, 1),
                ),
                (1, 2, 0, 2),
            )
        )

    # -------------------------------------------------------------- helpers

    def _format_args(self, args):
        if len(args) == 1:
            return str(next(iter(args.values())))
        return json.dumps(args)

    def _format_result(self, result):
        lines = result.strip().splitlines() or ["(no output)"]
        shown = lines[:MAX_TOOL_OUTPUT_LINES]
        body = Text("\n".join(shown), style=MUTED)
        hidden = len(lines) - len(shown)
        if hidden > 0:
            body.append(f"\n… {hidden} more lines", style=f"italic {TOOL}")
        return body

    def _write_view(self, args, result):
        """write_file: path in the header, highlighted code in the body."""
        path, content = args["path"], args["content"]
        lines = content.splitlines()

        header = Text.assemble(
            ("write_file ", f"bold {TOOL}"),
            (path, "bold"),
            (f"  ·  {len(lines)} lines", MUTED),
        )

        shown = "\n".join(lines[:MAX_WRITE_LINES])
        code = Syntax(
            shown,
            Syntax.guess_lexer(path, shown),
            theme="ansi_dark",  # follows your terminal colours
            line_numbers=True,
            word_wrap=True,
            background_color="default",
        )

        parts = [code]
        hidden = len(lines) - MAX_WRITE_LINES
        if hidden > 0:
            parts.append(Text(f"… {hidden} more lines", style=f"italic {TOOL}"))
        if result.startswith("Error"):
            parts.append(Text(result, style="red"))
        return header, Group(*parts)

    def _edit_view(self, args, result):
        """str_replace: a small red/green diff instead of raw arguments."""
        header = Text.assemble(
            ("str_replace ", f"bold {TOOL}"),
            (args["path"], "bold"),
        )

        diff = Text()
        old = args["old_str"].splitlines() or [""]
        new = args["new_str"].splitlines() or [""]
        for line in old[:MAX_WRITE_LINES]:
            diff.append(f"- {line}\n", style="red")
        for line in new[:MAX_WRITE_LINES]:
            diff.append(f"+ {line}\n", style="green")
        diff.rstrip()

        parts = [diff]
        hidden = max(len(old) - MAX_WRITE_LINES, 0) + max(len(new) - MAX_WRITE_LINES, 0)
        if hidden:
            parts.append(Text(f"… {hidden} more lines", style=f"italic {TOOL}"))
        if result.startswith("Error"):
            parts.append(Text(result, style="red"))
        return header, Group(*parts)


ui = UI()