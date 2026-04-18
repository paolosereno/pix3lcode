#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import argparse
import glob as glob_module
from datetime import datetime
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory

DEFAULTS = {
    "base_url": "http://10.5.0.2:1234/v1",
    "model": "qwen/qwen3-5b",
    "system_prompt": (
        "You are an AI assistant expert in programming and Linux systems. "
        "You have access to tools to read/write files, execute shell commands, and search code. "
        "Use these tools when needed. Before executing destructive commands, warn the user."
    ),
    "sessions_dir": "~/.pix3lcode_sessions",
    "shell_timeout": 60,
    "api_timeout": 120,
    "api_retries": 3,
    "context_limit": 80000,
    "context_warn_threshold": 0.70,
}

CONFIG_PATHS = [
    os.path.join(os.getcwd(), "pix3lcode_config.json"),
    os.path.expanduser("~/.pix3lcode_config.json"),
]


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    for path in reversed(CONFIG_PATHS):  # home first, then local (overrides)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception as e:
                print(f"Warning: cannot read {path}: {e}")
    return cfg


cfg = load_config()

SESSIONS_DIR = os.path.expanduser(cfg["sessions_dir"])

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")

parser = argparse.ArgumentParser(description="Pix3lCode — LM Studio client")
parser.add_argument("--model", "-m", default=cfg["model"], help="Model name to use")
parser.add_argument("--resume", "-r", nargs="?", const="last", metavar="ID",
                    help="Resume the last session or the one with the given ID")
parser.add_argument("--config", "-c", metavar="FILE", help="Path to an alternative config file")
parser.add_argument("--profile", "-p", metavar="NAME", help="Profile to use (file in profiles/<name>.json)")
parser.add_argument("--yes", "-y", action="store_true", help="Auto-confirm dangerous shell commands")
parser.add_argument("prompt_text", nargs="?", metavar="PROMPT", help="Non-interactive mode: run prompt and exit")
args = parser.parse_args()

if args.config:
    if os.path.exists(args.config):
        try:
            with open(args.config, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"Error in config file: {e}")
    else:
        print(f"Config file not found: {args.config}")

if args.profile:
    profile_path = os.path.join(PROFILES_DIR, f"{args.profile}.json")
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"Error in profile '{args.profile}': {e}")
    else:
        print(f"Profile '{args.profile}' not found in {PROFILES_DIR}/")
        sys.exit(1)

# --model from CLI overrides profile only if explicitly passed
if args.model != cfg["model"] or not args.profile:
    MODEL = args.model
else:
    MODEL = cfg["model"]
BASE_URL = cfg["base_url"]

SYSTEM_PROMPT = cfg["system_prompt"]

client = OpenAI(base_url=BASE_URL, api_key="lm-studio")
console = Console()

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from the filesystem",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path of the file to read"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file on the filesystem",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path of the file to write"},
                    "content": {"type": "string", "description": "Content to write to the file"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and folders in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (default: current directory)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": "Execute a Linux shell command and return stdout and stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "workdir": {
                        "type": "string",
                        "description": "Working directory (optional, default: current directory)",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_file",
            "description": (
                "Modify a specific part of a file by replacing an exact string with new text. "
                "Prefer this tool over write_file when changing only a portion of a file. "
                "The text to replace must be exact and unique in the file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path of the file to modify"},
                    "old_string": {"type": "string", "description": "Exact text to replace (must be unique in the file)"},
                    "new_string": {"type": "string", "description": "New text that will replace old_string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show the status of the current git repository (branch, modified, staged, untracked files)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository directory (default: current directory)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show differences in the git repository. Use staged=true to see changes already in staging (git diff --cached).",
            "parameters": {
                "type": "object",
                "properties": {
                    "staged": {
                        "type": "boolean",
                        "description": "If true show staged changes (--cached), otherwise unstaged changes (default: false)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Specific file or directory (optional)",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Repository directory (default: current directory)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Show the commit history of the git repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_count": {
                        "type": "integer",
                        "description": "Maximum number of commits to show (default: 10)",
                    },
                    "oneline": {
                        "type": "boolean",
                        "description": "Show each commit on one line (default: true)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Filter commits touching this file/directory (optional)",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Repository directory (default: current directory)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": (
                "Run git add and git commit with the given message. "
                "Always asks the user for confirmation before proceeding. "
                "Use files to specify which files to add (default: all tracked modified files)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Commit message",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files to stage (default: git add -u for all tracked files)",
                    },
                    "add_all": {
                        "type": "boolean",
                        "description": "If true run git add -A (includes new untracked files, default: false)",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Repository directory (default: current directory)",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Search for a text pattern in files of a directory (like grep). "
                "Returns matching lines with file name and line number. "
                "Use this tool to find functions, variables or patterns in code without reading all files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern (regex supported)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search in (default: current directory)",
                    },
                    "glob": {
                        "type": "string",
                        "description": "File filter, e.g. '*.py', '*.js' (default: all files)",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Case-sensitive search (default: false)",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Number of context lines before and after each match (default: 0)",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]


def _read_file(path: str) -> str:
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"ERROR: {e}"


def _write_file(path: str, content: str) -> str:
    try:
        expanded = os.path.expanduser(path)
        parent = os.path.dirname(expanded)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(expanded, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File written successfully: {path} ({len(content)} characters)"
    except Exception as e:
        return f"ERROR: {e}"


def _list_directory(path: str = ".") -> str:
    try:
        expanded = os.path.expanduser(path)
        entries = sorted(os.listdir(expanded))
        lines = []
        for e in entries:
            full = os.path.join(expanded, e)
            tag = "/" if os.path.isdir(full) else ""
            lines.append(f"{e}{tag}")
        return "\n".join(lines) if lines else "(empty)"
    except Exception as e:
        return f"ERROR: {e}"


DANGEROUS_PATTERNS = [
    r"\brm\b", r"\bdd\b", r"\bmkfs\b", r"\bshred\b", r"\btruncate\b",
    r"\bsudo\b", r"\bsu\b", r"\bchmod\b", r"\bchown\b",
    r"\bkill\b", r"\bpkill\b", r"\bkillall\b",
    r"\bmv\b.*\/", r"\bformat\b", r"\bfdisk\b", r"\bparted\b",
    r">\s*/", r"\| ?tee\b",
]


def _is_dangerous(command: str) -> bool:
    import re
    return any(re.search(p, command) for p in DANGEROUS_PATTERNS)


def _execute_shell(command: str, workdir: str | None = None) -> str:
    if _is_dangerous(command):
        if args.yes:
            console.print(f"\n  [bold yellow]⚠ Dangerous command executed (--yes):[/bold yellow] [yellow]{command}[/yellow]")
        else:
            console.print(
                f"\n  [bold red]⚠ Potentially dangerous command:[/bold red]\n"
                f"  [yellow]{command}[/yellow]"
            )
            try:
                answer = prompt("  Execute? [y/N]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                answer = "n"
            if answer not in ("y", "yes"):
                return "Execution cancelled by user."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=cfg["shell_timeout"],
            cwd=workdir,
        )
        out = result.stdout.rstrip()
        err = result.stderr.rstrip()
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr]\n{err}")
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out ({cfg['shell_timeout']}s)"
    except Exception as e:
        return f"ERROR: {e}"


def _patch_file(path: str, old_string: str, new_string: str) -> str:
    try:
        expanded = os.path.expanduser(path)
        with open(expanded, "r", encoding="utf-8") as f:
            content = f.read()
        if old_string not in content:
            return f"ERROR: text not found in '{path}'. Make sure the text to replace is exact."
        count = content.count(old_string)
        if count > 1:
            return f"ERROR: text appears {count} times in the file. Provide more context to make it unique."
        new_content = content.replace(old_string, new_string, 1)
        with open(expanded, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"File patched successfully: {path}"
    except FileNotFoundError:
        return f"ERROR: file not found '{path}'"
    except Exception as e:
        return f"ERROR: {e}"


def _search_files(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    case_sensitive: bool = False,
    context_lines: int = 0,
) -> str:
    cmd = ["grep", "-rn"]
    if not case_sensitive:
        cmd.append("-i")
    if context_lines > 0:
        cmd.extend([f"-C{context_lines}"])
    if glob:
        cmd.extend(["--include", glob])
    cmd.extend([pattern, os.path.expanduser(path)])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = result.stdout.rstrip()
        if not out:
            return "No results found."
        lines = out.splitlines()
        if len(lines) > 200:
            return "\n".join(lines[:200]) + f"\n[…{len(lines) - 200} lines truncated]"
        return out
    except subprocess.TimeoutExpired:
        return "ERROR: search timed out (30s)"
    except Exception as e:
        return f"ERROR: {e}"


def _git_status(path: str = ".") -> str:
    try:
        cwd = os.path.expanduser(path)
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=cwd
        ).stdout.strip() or "HEAD detached"
        status = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, cwd=cwd
        )
        if status.returncode != 0:
            return f"ERROR: {status.stderr.strip()}"
        body = status.stdout.strip() or "(no changes)"
        return f"Branch: {branch}\n\n{body}"
    except Exception as e:
        return f"ERROR: {e}"


def _git_diff(staged: bool = False, path: str | None = None, workdir: str = ".") -> str:
    try:
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--cached")
        if path:
            cmd.extend(["--", path])
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=os.path.expanduser(workdir), timeout=30
        )
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        out = result.stdout.strip()
        if not out:
            return "(no diff)"
        lines = out.splitlines()
        if len(lines) > 300:
            return "\n".join(lines[:300]) + f"\n[…{len(lines) - 300} lines truncated]"
        return out
    except Exception as e:
        return f"ERROR: {e}"


def _git_log(max_count: int = 10, oneline: bool = True, path: str | None = None, workdir: str = ".") -> str:
    try:
        cmd = ["git", "log", f"-{max_count}"]
        if oneline:
            cmd.append("--oneline")
        else:
            cmd.extend(["--format=%h %an %ad%n%s%n", "--date=short"])
        if path:
            cmd.extend(["--", path])
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=os.path.expanduser(workdir), timeout=15
        )
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stdout.strip() or "(no commits)"
    except Exception as e:
        return f"ERROR: {e}"


def _git_commit(message: str, files: list | None = None, add_all: bool = False, workdir: str = ".") -> str:
    cwd = os.path.expanduser(workdir)
    if files:
        files_str = " ".join(f'"{f}"' for f in files)
        preview_add = f"git add {files_str}"
    elif add_all:
        preview_add = "git add -A"
    else:
        preview_add = "git add -u"

    console.print(
        f"\n  [bold yellow]⚠ Git commit:[/bold yellow]\n"
        f"  [dim]{preview_add}[/dim]\n"
        f"  [dim]git commit -m \"{message}\"[/dim]"
    )
    try:
        answer = prompt("  Proceed? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        answer = "n"
    if answer not in ("y", "yes"):
        return "Commit cancelled by user."

    try:
        if files:
            add_result = subprocess.run(
                ["git", "add", "--"] + files,
                capture_output=True, text=True, cwd=cwd
            )
        elif add_all:
            add_result = subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, text=True, cwd=cwd
            )
        else:
            add_result = subprocess.run(
                ["git", "add", "-u"],
                capture_output=True, text=True, cwd=cwd
            )
        if add_result.returncode != 0:
            return f"ERROR (git add): {add_result.stderr.strip()}"

        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, cwd=cwd
        )
        if commit_result.returncode != 0:
            return f"ERROR (git commit): {commit_result.stderr.strip()}"
        return commit_result.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


TOOL_DISPATCH = {
    "read_file": lambda a: _read_file(a["path"]),
    "write_file": lambda a: _write_file(a["path"], a["content"]),
    "patch_file": lambda a: _patch_file(a["path"], a["old_string"], a["new_string"]),
    "list_directory": lambda a: _list_directory(a.get("path", ".")),
    "execute_shell": lambda a: _execute_shell(a["command"], a.get("workdir")),
    "search_files": lambda a: _search_files(
        a["pattern"],
        a.get("path", "."),
        a.get("glob"),
        a.get("case_sensitive", False),
        a.get("context_lines", 0),
    ),
    "git_status": lambda a: _git_status(a.get("path", ".")),
    "git_diff": lambda a: _git_diff(a.get("staged", False), a.get("path"), a.get("workdir", ".")),
    "git_log": lambda a: _git_log(a.get("max_count", 10), a.get("oneline", True), a.get("path"), a.get("workdir", ".")),
    "git_commit": lambda a: _git_commit(a["message"], a.get("files"), a.get("add_all", False), a.get("workdir", ".")),
}


def run_tool(name: str, args: dict) -> str:
    handler = TOOL_DISPATCH.get(name)
    if handler is None:
        return f"Unknown tool: {name}"
    return handler(args)


def _has_user_message(messages: list) -> bool:
    return any(
        (m["role"] if isinstance(m, dict) else m.role) == "user"
        for m in messages
    )


def _api_call_with_retry(messages: list) -> object:
    import time
    retries = int(cfg["api_retries"])
    timeout = int(cfg["api_timeout"])
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                timeout=timeout,
            )
        except Exception as e:
            err_str = str(e)
            # LM Studio: template requires at least one user message
            if "No user query found" in err_str and not _has_user_message(messages):
                console.print(
                    "  [yellow]⚠ Model template requires a user message. "
                    "Adding one automatically.[/yellow]"
                )
                messages.insert(1, {"role": "user", "content": "Continue."})
                continue
            last_exc = e
            if attempt < retries:
                wait = 2 ** attempt
                console.print(f"  [yellow]Attempt {attempt}/{retries} failed ({e}). Retrying in {wait}s…[/yellow]")
                time.sleep(wait)
    raise last_exc


def _check_context(total_prompt_tokens: int) -> None:
    limit = int(cfg["context_limit"])
    threshold = float(cfg["context_warn_threshold"])
    if limit <= 0:
        return
    usage_ratio = total_prompt_tokens / limit
    if usage_ratio >= 1.0:
        console.print(
            f"  [bold red]⚠ Context exhausted![/bold red] "
            f"[red]{total_prompt_tokens:,} / {limit:,} tokens. Use /compact or /clear.[/red]"
        )
    elif usage_ratio >= threshold:
        pct = int(usage_ratio * 100)
        console.print(
            f"  [bold yellow]⚠ Context at {pct}%[/bold yellow] "
            f"[yellow]({total_prompt_tokens:,} / {limit:,} tokens). "
            f"Consider /compact to free up space.[/yellow]"
        )


def agent_loop(messages: list) -> tuple[str, int, int]:
    """Returns (reply, total_prompt_tokens, total_completion_tokens)."""
    total_prompt = 0
    total_completion = 0

    while True:
        response = _api_call_with_retry(messages)

        if response.usage:
            total_prompt += response.usage.prompt_tokens
            total_completion += response.usage.completion_tokens

        choice = response.choices[0]
        msg = choice.message

        if not msg.tool_calls:
            content = msg.content or ""
            messages.append({"role": "assistant", "content": content})
            return content, total_prompt, total_completion

        messages.append(msg)

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            console.print(f"\n  [bold yellow]⚙ Tool:[/bold yellow] [cyan]{name}[/cyan]  {args}")
            result = run_tool(name, args)

            preview = result if len(result) <= 300 else result[:300] + "\n[…truncated]"
            console.print(f"  [dim]{preview}[/dim]")

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


def compact_messages(messages: list) -> list:
    system = messages[0]
    conversation = messages[1:]
    if not conversation:
        console.print("[dim]Nothing to compact.[/dim]")
        return messages

    history_text = []
    for m in conversation:
        role = m["role"] if isinstance(m, dict) else m.role
        if role == "tool":
            continue
        content = m["content"] if isinstance(m, dict) else m.content
        if content:
            history_text.append(f"{role.upper()}: {content}")

    summary_prompt = [
        system,
        {
            "role": "user",
            "content": (
                "Summarize the following conversation concisely, "
                "keeping all important technical details, "
                "decisions made, modified files and project context. "
                "The summary will be used as a starting point to continue the work.\n\n"
                + "\n\n".join(history_text)
            ),
        },
    ]

    console.print("[dim]Compacting conversation…[/dim]")
    response = client.chat.completions.create(model=MODEL, messages=summary_prompt)
    summary = response.choices[0].message.content or ""

    new_messages = [
        system,
        {"role": "user", "content": "Continue from the summary of the previous conversation."},
        {"role": "assistant", "content": f"[Summary of previous conversation]\n\n{summary}"},
    ]
    console.print(Panel(Markdown(summary), title="[bold]Summary[/bold]", border_style="dim"))
    return new_messages


# ── Session management ────────────────────────────────────────────────────────

def _serialize_messages(messages: list) -> list:
    """Convert messages to plain dicts (handles pydantic objects from the SDK)."""
    result = []
    for m in messages:
        if isinstance(m, dict):
            result.append(m)
        else:
            d = {"role": m.role, "content": m.content or ""}
            if hasattr(m, "tool_calls") and m.tool_calls:
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in m.tool_calls
                ]
            result.append(d)
    return result


def _first_user_message(messages: list) -> str:
    for m in messages:
        role = m["role"] if isinstance(m, dict) else m.role
        content = m["content"] if isinstance(m, dict) else (m.content or "")
        if role == "user" and content:
            return content[:60].replace("\n", " ")
    return "empty session"


def save_session(messages: list, session_id: str) -> None:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    data = {
        "id": session_id,
        "model": MODEL,
        "saved_at": datetime.now().isoformat(),
        "preview": _first_user_message(messages),
        "messages": _serialize_messages(messages),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_session(session_id: str) -> list | None:
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["messages"]


def list_sessions(n: int = 10) -> list[dict]:
    files = sorted(
        glob_module.glob(os.path.join(SESSIONS_DIR, "*.json")),
        key=os.path.getmtime,
        reverse=True,
    )
    sessions = []
    for f in files[:n]:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            sessions.append(data)
        except Exception:
            pass
    return sessions


def delete_session(session_id: str) -> bool:
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def _print_sessions_table(sessions: list) -> None:
    table = Table(title="Recent sessions", border_style="cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Date", style="dim")
    table.add_column("Model", style="green")
    table.add_column("Preview")
    for i, s in enumerate(sessions, 1):
        saved_at = s.get("saved_at", "")[:16].replace("T", " ")
        table.add_row(str(i), s["id"], saved_at, s.get("model", "?"), s.get("preview", ""))
    console.print(table)


def pick_session() -> list | None:
    """Show recent sessions and ask the user which one to resume or delete."""
    sessions = list_sessions()
    if not sessions:
        console.print("[dim]No saved sessions.[/dim]")
        return None

    while True:
        _print_sessions_table(sessions)
        console.print("[dim]Enter a number to resume, d<n> to delete (e.g. d1), Enter to cancel[/dim]")

        try:
            choice = prompt("Choice: ").strip()
        except (KeyboardInterrupt, EOFError):
            return None

        if not choice:
            return None

        # delete: d1, d 1, D1…
        if choice.lower().startswith("d"):
            num_str = choice[1:].strip()
            if num_str.isdigit():
                idx = int(num_str) - 1
                if 0 <= idx < len(sessions):
                    sid = sessions[idx]["id"]
                    delete_session(sid)
                    console.print(f"[dim]Session {sid} deleted.[/dim]")
                    sessions = list_sessions()
                    if not sessions:
                        console.print("[dim]No sessions left.[/dim]")
                        return None
                    continue
            console.print("[red]Invalid number.[/red]")
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                return load_session(sessions[idx]["id"])
            console.print("[red]Invalid number.[/red]")
            continue

        return load_session(choice)


# ── Project context ───────────────────────────────────────────────────────────

def load_project_context() -> str | None:
    """Read CONTEXT.md from the current directory if it exists."""
    path = os.path.join(os.getcwd(), "CONTEXT.md")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return None


def build_system_prompt() -> str:
    context = load_project_context()
    if not context:
        return SYSTEM_PROMPT
    return (
        SYSTEM_PROMPT
        + "\n\n## Project context\n\n"
        + context
    )


# ── Non-interactive mode ──────────────────────────────────────────────────────

def run_once(user_input: str) -> None:
    """Run a single prompt and print the response to stdout."""
    system_prompt = build_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    try:
        reply, _, _ = agent_loop(messages)
        print(reply)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # non-interactive mode
    if args.prompt_text:
        run_once(args.prompt_text)
        return

    # read from stdin if piped (e.g. cat file.py | ./pix3lcode.sh "explain this")
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read().strip()
        if stdin_content:
            combined = f"{args.prompt_text or ''}\n\n{stdin_content}".strip()
            run_once(combined)
            return

    system_prompt = build_system_prompt()
    messages: list = [{"role": "system", "content": system_prompt}]
    resumed = False

    if args.resume:
        if args.resume == "last":
            loaded = pick_session()
        else:
            loaded = load_session(args.resume)
            if loaded is None:
                console.print(f"[red]Session '{args.resume}' not found.[/red]")

        if loaded:
            messages = loaded
            # reuse the resumed session ID so it gets overwritten on save
            files = sorted(
                glob_module.glob(os.path.join(SESSIONS_DIR, "*.json")),
                key=os.path.getmtime,
                reverse=True,
            )
            if files and args.resume == "last":
                session_id = os.path.splitext(os.path.basename(files[0]))[0]
            elif args.resume != "last":
                session_id = args.resume
            resumed = True
            console.print(f"[dim]Session resumed: {session_id}[/dim]")

    console.print(
        Panel.fit(
            f"[bold cyan]Pix3lCode[/bold cyan] — LM Studio  [dim]{BASE_URL}[/dim]\n"
            f"Model: [green]{MODEL}[/green]"
            + (f"  profile: [magenta]{args.profile}[/magenta]" if args.profile else "")
            + (f"  [dim]session: {session_id}[/dim]" if resumed else "")
            + (f"\n[dim]Project context: CONTEXT.md loaded[/dim]" if load_project_context() else "") + "\n"
            "[dim]/help  |  /clear  |  /compact  |  /sessions  |  /exit  |  Ctrl+C[/dim]",
            border_style="cyan",
        )
    )

    history_file = os.path.expanduser("~/.pix3lcode_history")
    total_prompt_tokens = 0
    total_completion_tokens = 0

    while True:
        try:
            user_input = prompt(
                "\nYou: ",
                history=FileHistory(history_file),
                multiline=False,
            ).strip()
        except (KeyboardInterrupt, EOFError):
            save_session(messages, session_id)
            console.print(f"\n[dim]Session saved ({session_id}). Goodbye![/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/exit", "/quit"):
            save_session(messages, session_id)
            console.print(f"[dim]Session saved ({session_id}). Goodbye![/dim]")
            break

        if user_input.lower() == "/model":
            console.print(f"[bold]Model:[/bold] [green]{MODEL}[/green]  [dim]{BASE_URL}[/dim]")
            continue

        if user_input.lower() == "/tokens":
            total = total_prompt_tokens + total_completion_tokens
            console.print(
                f"[bold]Session tokens:[/bold]  "
                f"prompt [cyan]{total_prompt_tokens:,}[/cyan]  "
                f"completion [cyan]{total_completion_tokens:,}[/cyan]  "
                f"total [bold cyan]{total:,}[/bold cyan]"
            )
            continue

        if user_input.lower() == "/sessions":
            loaded = pick_session()
            if loaded:
                messages = loaded
                console.print("[dim]Session loaded.[/dim]")
            continue

        if user_input.lower() == "/help":
            console.print(Panel(
                "[bold]/help[/bold]      show this message\n"
                "[bold]/model[/bold]     show the active model and URL\n"
                "[bold]/tokens[/bold]    show token usage for the current session\n"
                "[bold]/sessions[/bold]  list saved sessions (number=resume, d<n>=delete)\n"
                "[bold]/clear[/bold]     clear history and start a new session\n"
                "[bold]/compact[/bold]   summarize the conversation to free up context\n"
                "[bold]/init[/bold]      analyze the project and generate CONTEXT.md\n"
                "[bold]/exit[/bold]      save and exit\n\n"
                "[bold cyan]Available tools for the model:[/bold cyan]\n"
                "  [cyan]read_file[/cyan]      read a file\n"
                "  [cyan]write_file[/cyan]     write or create a file\n"
                "  [cyan]patch_file[/cyan]     modify only a part of a file (old→new)\n"
                "  [cyan]list_directory[/cyan] list files in a directory\n"
                "  [cyan]execute_shell[/cyan]  run a shell command (asks confirmation if dangerous)\n"
                "  [cyan]search_files[/cyan]   search text in files with regex (like grep)\n"
                "  [cyan]git_status[/cyan]     show git repository status\n"
                "  [cyan]git_diff[/cyan]       show diff (staged or unstaged)\n"
                "  [cyan]git_log[/cyan]        show commit history\n"
                "  [cyan]git_commit[/cyan]     run git add + commit (asks confirmation)\n\n"
                "[bold cyan]Resume from command line:[/bold cyan]\n"
                "  [dim]./pix3lcode.sh --resume[/dim]              resume from list\n"
                "  [dim]./pix3lcode.sh --resume 20240418_1230[/dim]  resume a specific session\n\n"
                f"[bold]Model:[/bold] [green]{MODEL}[/green]  [dim]{BASE_URL}[/dim]",
                title="[bold]Available commands[/bold]",
                border_style="cyan",
            ))
            continue

        if user_input.lower() == "/clear":
            messages = [{"role": "system", "content": build_system_prompt()}]
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            console.print("[dim]History cleared. New session started.[/dim]")
            continue

        if user_input.lower() == "/compact":
            with console.status("[bold blue]Compacting…[/bold blue]", spinner="dots"):
                try:
                    messages = compact_messages(messages)
                except KeyboardInterrupt:
                    console.print("\n[yellow]Cancelled.[/yellow]")
                except Exception as e:
                    console.print(f"[red]Error during /compact: {e}[/red]")
            continue

        if user_input.lower() == "/init":
            context_path = os.path.join(os.getcwd(), "CONTEXT.md")
            if os.path.exists(context_path):
                try:
                    answer = prompt("  CONTEXT.md already exists. Overwrite? [y/N]: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    answer = "n"
                if answer not in ("y", "yes"):
                    console.print("[dim]Operation cancelled.[/dim]")
                    continue

            init_prompt = (
                f"Analyze the project in directory '{os.getcwd()}'. "
                "Use list_directory and read_file to explore the structure, "
                "read the main files (README, config files, entry points, etc.) "
                "and understand the technologies, conventions and architecture. "
                "Then write a concise CONTEXT.md file (max 300 words) with these sections:\n"
                "- Project name and brief description\n"
                "- Main technologies and dependencies\n"
                "- Directory structure\n"
                "- Entry points and main files\n"
                "- Code conventions (if detectable)\n\n"
                "Use write_file to save CONTEXT.md in the current directory."
            )
            messages.append({"role": "user", "content": init_prompt})
            with console.status("[bold blue]Analyzing project…[/bold blue]", spinner="dots"):
                try:
                    reply, prompt_tok, completion_tok = agent_loop(messages)
                except KeyboardInterrupt:
                    console.print("\n[yellow]Cancelled.[/yellow]")
                    messages.pop()
                    continue
                except Exception as e:
                    console.print(f"[red]Error during /init: {e}[/red]")
                    messages.pop()
                    continue
            total_prompt_tokens += prompt_tok
            total_completion_tokens += completion_tok
            console.print("\n[bold blue]Assistant:[/bold blue]")
            console.print(Markdown(reply))
            if os.path.exists(context_path):
                console.print(f"[bold green]CONTEXT.md generated.[/bold green] It will be loaded automatically in future sessions.")
            save_session(messages, session_id)
            continue

        messages.append({"role": "user", "content": user_input})

        with console.status("[bold blue]Thinking…[/bold blue]", spinner="dots"):
            try:
                reply, prompt_tok, completion_tok = agent_loop(messages)
            except KeyboardInterrupt:
                console.print("\n[yellow]Cancelled.[/yellow]")
                messages.pop()
                continue
            except Exception as e:
                console.print(f"[red]API error: {e}[/red]")
                messages.pop()
                continue

        total_prompt_tokens += prompt_tok
        total_completion_tokens += completion_tok
        total_tok = total_prompt_tokens + total_completion_tokens

        console.print("\n[bold blue]Assistant:[/bold blue]")
        console.print(Markdown(reply))
        _check_context(total_prompt_tokens)
        console.print(
            f"  [dim]tokens: prompt {prompt_tok:,} | completion {completion_tok:,} | "
            f"session {total_tok:,}[/dim]"
        )

        # auto-save after each exchange
        save_session(messages, session_id)


if __name__ == "__main__":
    main()
