# function tool

import json
import os
import subprocess

from src.core.context import note_read
from src.safety.sandbox import looks_like_dev_server, run


# bash function
def bash(command: str) -> str:
    # run bash commands
    try:
        result = run(command)
    except subprocess.TimeoutExpired:
        if looks_like_dev_server(command):
            return (
                f"'{command}' looks like a dev server or watcher - a process "
                "that runs forever rather than finishing. This tool can only "
                "run commands to completion and return their output; it has "
                "no way to keep a background server alive once this call "
                "returns. It was stopped after a few seconds - if nothing "
                "above looks like an error, it started fine. Tell the user "
                "to run this command themselves in their own terminal to use "
                "it; do not try running it again here."
            )
        return (
            f"'{command}' did not finish in time and was stopped. If this is "
            "a long-running process (a server, a watcher, something with no "
            "natural end), this tool cannot run it - tell the user to run it "
            "themselves instead of retrying."
        )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        # Without this an empty failing command looks identical to success,
        # and the model keeps retrying without knowing it failed.
        output += f"\n[exit code {result.returncode}]"
    return output


# read_file function
def read_file(path: str) -> str:
    # read a file and return its content
    if not os.path.isfile(path):
        return f"Error: {path} does not exist or is not a file."
    note_read(path)  # updates the mtime whenever the read_file tool is used
    with open(path) as f:
        return f.read()


# write file function
def write_file(path: str, content: str) -> str:
    # create a file ,or overwrite it if it already exists
    with open(path, "w") as f:
        f.write(content)
    return f"Wrote {path}"


# replace a code function
def str_replace(path, old_str, new_str, allow_multi_edit=False):
    if not os.path.isfile(path):
        return f"Error: {path} does not exist or is not a file."
    # swap exact text in a file, old_str must match exactly once
    with open(path) as f:
        content = f.read()

    count = content.count(old_str)
    if count == 0:
        return f"Error: old_str was not found in {path}"
    if count > 1 and not allow_multi_edit:
        return (
            f"Error : old_str matches {count} times in {path}."
            "Add surrounding lines to make it unique, "
            "or set allow_multi_edit to replace them all."
        )

    with open(path, "w") as f:
        f.write(content.replace(old_str, new_str))
    return f"Replaced {count} match(es) in {path}"


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command and return its output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file and return its contents",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "path to the file to read",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a file, or overwrite it if it already exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File to write"},
                    "content": {"type": "string", "description": "The full contents"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "str_replace",
            "description": (
                "Replace exact text in a file. old_str must appear exactly once, "
                "so include surrounding lines if needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File to edit"},
                    "old_str": {"type": "string", "description": "Exact text to find"},
                    "new_str": {
                        "type": "string",
                        "description": "Text to put in its place",
                    },
                    "allow_multi_edit": {
                        "type": "boolean",
                        "description": "Replace every match instead of failing",
                    },
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
]

TOOLS = {
    "bash": bash,
    "read_file": read_file,
    "write_file": write_file,
    "str_replace": str_replace,
}


def execute(tool_call, tools=None):
    lookup = tools or TOOLS
    args = json.loads(tool_call.function.arguments)
    try:
        result = lookup[tool_call.function.name](**args)
    except Exception as e:
        result = f"Error: {type(e).__name__}: {e}"
    return args, result
