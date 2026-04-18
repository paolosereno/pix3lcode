import os
import re
import subprocess
from config import AppContext

DANGEROUS_PATTERNS = [
    r"\brm\b", r"\bdd\b", r"\bmkfs\b", r"\bshred\b", r"\btruncate\b",
    r"\bsudo\b", r"\bsu\b", r"\bchmod\b", r"\bchown\b",
    r"\bkill\b", r"\bpkill\b", r"\bkillall\b",
    r"\bmv\b.*\/", r"\bformat\b", r"\bfdisk\b", r"\bparted\b",
    r">\s*/", r"\| ?tee\b",
    r"\bpip\b.*install\b", r"--break-system-packages",
    r"\bapt\b", r"\bapt-get\b", r"\bdnf\b", r"\byum\b",
    r"\bcurl\b.*\|\s*(bash|sh)\b", r"\bwget\b.*\|\s*(bash|sh)\b",
]

TOOL_DEFINITIONS = [
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


def read_file(path: str, ctx: AppContext) -> str:
    try:
        expanded = os.path.expanduser(path)
        size = os.path.getsize(expanded)
        limit = int(ctx.cfg.get("read_file_limit", 100_000))
        with open(expanded, "r", encoding="utf-8") as f:
            content = f.read(limit)
        if size > limit:
            truncated_kb = limit // 1024
            total_kb = size // 1024
            content += f"\n\n[…file truncated: showing first {truncated_kb}KB of {total_kb}KB]"
            ctx.console.print(f"  [yellow]⚠ read_file: {path} is {total_kb}KB, truncated to {truncated_kb}KB[/yellow]")
        return content
    except Exception as e:
        return f"ERROR: {e}"


def write_file(path: str, content: str, ctx: AppContext) -> str:
    ctx.console.print(
        f"\n  [bold yellow]⚠ Write file:[/bold yellow] [cyan]{path}[/cyan] "
        f"[dim]({len(content)} characters)[/dim]"
    )
    if not ctx.confirm("  Proceed? [y/N]: "):
        return "Write cancelled by user."
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


def list_directory(path: str = ".", ctx: AppContext = None) -> str:
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


def _is_dangerous(command: str) -> bool:
    return any(re.search(p, command) for p in DANGEROUS_PATTERNS)


def execute_shell(command: str, workdir: str | None, ctx: AppContext) -> str:
    if _is_dangerous(command):
        if ctx.auto_yes:
            ctx.console.print(f"\n  [bold yellow]⚠ Dangerous command executed (--yes):[/bold yellow] [yellow]{command}[/yellow]")
        else:
            ctx.console.print(
                f"\n  [bold red]⚠ Potentially dangerous command:[/bold red]\n"
                f"  [yellow]{command}[/yellow]"
            )
            if not ctx.confirm("  Execute? [y/N]: "):
                return "Execution cancelled by user."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=ctx.cfg["shell_timeout"],
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
        return f"ERROR: command timed out ({ctx.cfg['shell_timeout']}s)"
    except Exception as e:
        return f"ERROR: {e}"


def patch_file(path: str, old_string: str, new_string: str, ctx: AppContext) -> str:
    ctx.console.print(
        f"\n  [bold yellow]⚠ Patch file:[/bold yellow] [cyan]{path}[/cyan]"
    )
    if not ctx.confirm("  Proceed? [y/N]: "):
        return "Patch cancelled by user."
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


def search_files(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    case_sensitive: bool = False,
    context_lines: int = 0,
    ctx: AppContext = None,
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


def make_dispatch(ctx: AppContext) -> dict:
    return {
        "read_file": lambda a: read_file(a["path"], ctx),
        "write_file": lambda a: write_file(a["path"], a["content"], ctx),
        "patch_file": lambda a: patch_file(a["path"], a["old_string"], a["new_string"], ctx),
        "list_directory": lambda a: list_directory(a.get("path", "."), ctx),
        "execute_shell": lambda a: execute_shell(a["command"], a.get("workdir"), ctx),
        "search_files": lambda a: search_files(
            a["pattern"],
            a.get("path", "."),
            a.get("glob"),
            a.get("case_sensitive", False),
            a.get("context_lines", 0),
            ctx,
        ),
    }
