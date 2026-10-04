"""Kernel-enforced limits on what bash can touch.

One policy - read anything, write only inside the project, no network - and a
different enforcement mechanism per OS. The idea ports; the mechanism never does.

One exception: package managers (bun, npm, pip, ...) cannot work without the
network and their download cache. Those commands still cannot write outside the
project, but they get the network and write access to the cache folders. They
are never auto-allowed by permissions.py, so you approve each one first.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path.cwd().resolve()
HOME = Path.home()

# First word of a command that needs the network to do its job.
NETWORK_COMMANDS = {
    "bun", "bunx", "npm", "npx", "pnpm", "yarn",
    "pip", "pip3", "uv", "uvx", "cargo",
}

# Dev servers, watchers and other processes that never exit on their own.
# subprocess.run always waits for the process to finish before returning,
# so a command like this only ever "completes" via the timeout - and
# --unshare-pid means even `cmd &` dies the instant the invoking shell
# exits, so there is no way to background one of these and keep it alive
# past this one tool call. Best this tool can do is fail fast and say so,
# rather than hang in silence for the full network timeout.
DEV_SERVER_PATTERN = re.compile(
    r"\b(dev|start|serve|watch|runserver)\b|nodemon|docker compose up(?!.*-d)",
    re.IGNORECASE,
)

# Caches those tools write to. The first group is created if missing (a fresh
# machine has no ~/.bun yet); the second is only used if it already exists.
CACHE_DIRS = [HOME / ".bun", HOME / ".npm", HOME / ".cache"]
OPTIONAL_CACHE_DIRS = [HOME / ".yarn", HOME / ".local" / "share" / "pnpm", HOME / ".cargo"]


def needs_network(command):
    """True if any part of a compound command starts with a package manager."""
    for part in re.split(r"&&|\|\||;|\|", command):
        words = part.split()
        if words and words[0] in NETWORK_COMMANDS:
            return True
    return False


def cache_dirs():
    for path in CACHE_DIRS:
        path.mkdir(parents=True, exist_ok=True)
    return [p for p in CACHE_DIRS + OPTIONAL_CACHE_DIRS if p.exists()]


def profile(network):
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec process-fork signal)",
        "(allow file-read*)",
        "(allow sysctl-read)",
        f'(allow file-write* (subpath "{PROJECT}") (literal "/dev/null"))',
    ]
    if network:
        lines += ["(allow network*)", "(allow mach-lookup)"]
        for path in cache_dirs():
            lines.append(f'(allow file-write* (subpath "{path}"))')
        # package managers stage downloads in the temp dir
        lines.append('(allow file-write* (subpath "/private/tmp") (subpath "/private/var/folders"))')
    else:
        lines.append("(deny network*)")
    lines.append(f'(deny file-write* (subpath "{PROJECT}/.git"))')
    return "\n".join(lines) + "\n"


def wrap(command, network=False):
    """Wrap a shell command in an OS sandbox. None means we have no sandbox."""
    if sys.platform == "darwin":
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".sb", delete=False)
        handle.write(profile(network))
        handle.close()
        return ["sandbox-exec", "-f", handle.name, "/bin/sh", "-c", command]

    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        args = [
            "bwrap",
            "--ro-bind", "/", "/",  # whole filesystem read-only...
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--bind", str(PROJECT), str(PROJECT),  # ...except the project, read-write
        ]
        # bwrap aborts if the source path is missing, and not every project
        # is a git repo - so only protect .git when it exists.
        git = PROJECT / ".git"
        if git.exists():
            args += ["--ro-bind", str(git), str(git)]  # .git back to read-only

        if network:
            for path in cache_dirs():
                args += ["--bind", str(path), str(path)]
        else:
            args.append("--unshare-net")  # no network

        args += ["--unshare-pid", "--die-with-parent", "/bin/sh", "-c", command]
        return args

    return None  # Windows, or Linux without bubblewrap


def name():
    if sys.platform == "darwin":
        return "seatbelt"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bubblewrap"
    return "none"


def looks_like_dev_server(command):
    """Best-effort guess, not a guarantee - a command we don't recognise as
    blocking will still hang for the full timeout, just like before."""
    return bool(DEV_SERVER_PATTERN.search(command))


def run(command, timeout=60):
    """Run a command, sandboxed when the OS lets us."""
    network = needs_network(command)
    if network:
        timeout = max(timeout, 300)  # installs are slow
    if looks_like_dev_server(command):
        # Overrides the network bump above - a server takes the same ~300s
        # to NOT finish as an install takes to actually finish, so without
        # this a dev server masquerades as a slow install for 5 minutes
        # before failing. 8s is enough to surface a startup error if there
        # is one.
        timeout = 8
    sandboxed = wrap(command, network)
    return subprocess.run(
        sandboxed or command,
        shell=sandboxed is None,
        capture_output=True,
        text=True,
        timeout=timeout,
        # Output is captured, so a hidden prompt (e.g. create-vite asking
        # "directory not empty, overwrite?") is invisible - you can't see
        # it or answer it, so it hangs until the timeout instead of failing
        # fast or just proceeding. Closing stdin makes an unexpected prompt
        # fail immediately; CI=1 is what create-vite, create-react-app and
        # most JS scaffolding tools check to skip that prompt and proceed
        # automatically instead of asking at all.
        stdin=subprocess.DEVNULL,
        env={**os.environ, "CI": "1", "npm_config_yes": "true"},
    )
