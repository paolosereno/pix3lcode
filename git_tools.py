import os
import subprocess
from config import AppContext

TOOL_DEFINITIONS = [
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
]


def git_status(path: str = ".", ctx: AppContext = None) -> str:
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


def git_diff(staged: bool = False, path: str | None = None, workdir: str = ".", ctx: AppContext = None) -> str:
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


def git_log(max_count: int = 10, oneline: bool = True, path: str | None = None, workdir: str = ".", ctx: AppContext = None) -> str:
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


def git_commit(message: str, files: list | None = None, add_all: bool = False, workdir: str = ".", ctx: AppContext = None) -> str:
    cwd = os.path.expanduser(workdir)
    if files:
        files_str = " ".join(f'"{f}"' for f in files)
        preview_add = f"git add {files_str}"
    elif add_all:
        preview_add = "git add -A"
    else:
        preview_add = "git add -u"

    ctx.console.print(
        f"\n  [bold yellow]⚠ Git commit:[/bold yellow]\n"
        f"  [dim]{preview_add}[/dim]\n"
        f"  [dim]git commit -m \"{message}\"[/dim]"
    )
    if not ctx.confirm("  Proceed? [y/N]: "):
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


def make_dispatch(ctx: AppContext) -> dict:
    return {
        "git_status": lambda a: git_status(a.get("path", "."), ctx),
        "git_diff": lambda a: git_diff(a.get("staged", False), a.get("path"), a.get("workdir", "."), ctx),
        "git_log": lambda a: git_log(a.get("max_count", 10), a.get("oneline", True), a.get("path"), a.get("workdir", "."), ctx),
        "git_commit": lambda a: git_commit(a["message"], a.get("files"), a.get("add_all", False), a.get("workdir", "."), ctx),
    }
