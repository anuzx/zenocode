import json
import os

from src import session
from src.commands import COMMANDS, handle
from src.commands import compact as run_compact
from src.core.compact import needed
from src.core.context import reminder
from src.core.history import cap, strip, sweep
from src.core.todos import TODO_SCHEMA, active_form, write_todos
from src.main import call_llm
from src.safety.permissions import check
from src.safety.sandbox import name as sandbox_name
from src.subagent import TASK_SCHEMA, task
from src.tools import TOOL_SCHEMAS, TOOLS, execute
from src.tui.ui import ui

MAX_STEPS = 30  # model calls per user message, so a failing loop cannot run forever

ALL_SCHEMAS = TOOL_SCHEMAS + [TODO_SCHEMA, TASK_SCHEMA]
ALL_TOOLS = {**TOOLS, "write_todos": write_todos, "task": task}

SYSTEM_PROMPT = f"""
You are a coding agent. Your job is to code. Always code.
Use the bash tool to inspect files.
Use write_file to create files and str_replace to edit them.
Answer back to the user once exploration is done.

For any task that takes more than one step, call write_todos first and plan it
out. Send the whole list every time you call it - it replaces the old one.
Keep exactly one task in_progress, mark it done the moment it is finished, and
move the next one to in_progress in the same call. Do not batch up completions
at the end. Skip the tool entirely for single-step tasks; it is noise there.

The current list is injected back to you every turn inside <todos> tags, so
that block - not the transcript - is the truth about where you are.

When you need to understand how something works - where a feature lives, how
data flows, what calls what - send a task subagent instead of grepping your
way there yourself. It explores in its own context window and hands you back
just the findings, so the search does not fill yours. It cannot see this
conversation, so write the question so it stands alone. Do all editing
yourself; the subagent only reads.

Long tool output is cut short, and the whole thing is written to a temp file
whose path is given at the cut. Page through it with head, tail, sed -n or
grep rather than asking for it again. That file only exists for the current
turn, so read it now or re-run the command later.

Each bash call runs in a fresh shell, so `cd` does not carry over to the next
call. Chain what belongs together: `cd backend && bun add express`.

Never run commands that wait for input. Pass the non-interactive flags
(`bun init -y`, `npm init -y`, `npm create vite@latest app -- --template react`).
Package managers (bun, npm, pip) get network access, but only after the user
approves the command.

If the same command fails twice, stop. Explain the error to the user instead
of retrying it a third time. Read [exit code N] at the end of bash output: it
means the command failed, even when nothing else was printed.

Never run a dev server, watcher, or anything else that runs forever (`bun
dev`, `npm start`, `vite`, `nodemon`, `flask run`, `manage.py runserver`,
`docker compose up` without `-d`) through bash. This tool runs a command to
completion and returns its output - it has no way to keep a server alive
after the call returns, and no way to background one either. Scaffold and
configure the project, then tell the user the exact command to run themselves
in their own terminal.

Your current working directory is: {os.getcwd()}

"""


def main():
    ui.start()
    ui.banner(sandbox_name())
    messages = session.open_session(session.CURRENT) or []
    if messages:
        ui.replay(messages)

    while True:
        user_input = ui.ask()
        if not user_input:
            break

        if user_input.startswith("/"):
            messages = handle(user_input.split()[0], messages)
            continue

        messages.append({"role": "user", "content": user_input})
        session.save(messages)

        steps = 0
        while True:
            steps += 1
            if steps > MAX_STEPS:
                ui.note(
                    f"stopped after {MAX_STEPS} steps in one turn - "
                    "tell me to continue, or change the plan"
                )
                strip(messages)
                sweep()
                session.save(messages)
                break

            with ui.working(active_form()):
                message, usage = call_llm(messages + [reminder()], tools=ALL_SCHEMAS)
            messages.append(message.model_dump(exclude_none=True))
            session.save(messages)
            ui.usage(usage)

            if message.content:
                ui.agent(message.content)
            if not message.tool_calls:
                # The turn is over: whatever tool output is sitting unlocked
                # in the transcript is now just history, not something the
                # model needs in full any more. Shrink it, and drop the temp
                # files cap() spilled for those results, before waiting on
                # the next user message.
                strip(messages)
                sweep()
                session.save(messages)
                break

            for tool_call in message.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as error:
                    # A weaker model can fail to escape a quote, backslash
                    # or raw newline inside a long argument (write_file's
                    # content is the usual culprit), producing JSON that
                    # breaks partway through. Tell the model, rather than
                    # letting an unhandled exception crash the whole
                    # program here - tools.execute() already guards its own
                    # copy of this same parse, but check() below needs the
                    # parsed args too, and ran unguarded until now.
                    result = (
                        f"Error: arguments were not valid JSON ({error}). This "
                        "usually means a string value - often write_file's "
                        "content - has an unescaped quote, backslash, or raw "
                        "newline. Re-emit the call with those escaped, or "
                        "split a large write_file into a smaller str_replace."
                    )
                    ui.tool(name, {}, result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": cap(result),
                        }
                    )
                    continue
                action, reason = check(name, args)
                if action == "deny":
                    result = f"Blocked by policy: {reason}"
                elif action == "ask" and not ui.approve(reason):
                    result = "User declined this action."
                elif name == "task":
                    # the subagent draws its own spinner and nested panels -
                    # two live Rich displays can't run at the same time
                    _, result = execute(tool_call, tools=ALL_TOOLS)
                else:
                    with ui.working(ui.phase(name, args)):
                        _, result = execute(tool_call, tools=ALL_TOOLS)
                ui.tool(name, args, result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": cap(result),
                    }
                )
            session.save(messages)

            # The request that just went out is the freshest read we have on
            # how full the window is. If it crossed the line, compact now,
            # before the next call, rather than waiting for /compact.
            if needed(usage):
                messages = run_compact(messages)


if __name__ == "__main__":
    main()
