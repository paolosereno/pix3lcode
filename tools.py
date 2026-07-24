import glob
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

_LINKER_RE = re.compile(
    r"undefined reference|vtable for|DSO missing|cannot find -l|ld returned",
    re.IGNORECASE,
)

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
                    "content": {"type": "string", "description": "Content to write to the file. Use real newline characters (not literal \\n escape sequences)."},
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
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": (
                "Find files by name pattern, not by content (like glob/find). "
                "Supports wildcards ('*.py') and recursive patterns ('**/*.test.js'). "
                "Returns matching paths, most recently modified first. "
                "Use this to locate files when you know (part of) the name but not the location, "
                "as an alternative to search_files (which matches file contents)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern, e.g. '*.py', '**/*.tsx', 'src/**/test_*.py'",
                    },
                    "path": {
                        "type": "string",
                        "description": "Base directory to search from (default: current directory)",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_known_files",
            "description": (
                "List all files read in this session with their sizes. "
                "Check this before re-reading a file to confirm it is already cached."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def _cache_store(ctx: AppContext, abs_path: str, content: str) -> None:
    """Insert or refresh a file entry in the LRU cache, evicting oldest if over limits."""
    max_files = int(ctx.cfg.get("file_cache_max_files", 50))
    max_bytes = int(ctx.cfg.get("file_cache_max_bytes", 10_000_000))
    size_bytes = len(content.encode("utf-8"))
    # Remove existing entry so re-insertion lands at the MRU end
    ctx.file_registry.pop(abs_path, None)
    current_bytes = sum(e["size"] for e in ctx.file_registry.values())
    while ctx.file_registry and (
        len(ctx.file_registry) >= max_files or current_bytes + size_bytes > max_bytes
    ):
        oldest = next(iter(ctx.file_registry))
        current_bytes -= ctx.file_registry[oldest]["size"]
        del ctx.file_registry[oldest]
    try:
        mtime = os.path.getmtime(abs_path)
    except OSError:
        mtime = 0.0
    ctx.file_registry[abs_path] = {"mtime": mtime, "size": size_bytes, "content": content}


def read_file(path: str, ctx: AppContext) -> str:
    try:
        expanded = os.path.abspath(os.path.expanduser(path))

        # Cache hit: one stat() call to check freshness, no disk read if unchanged
        if expanded in ctx.file_registry:
            entry = ctx.file_registry[expanded]
            try:
                if os.path.getmtime(expanded) == entry["mtime"]:
                    # Move to MRU end
                    ctx.file_registry[expanded] = ctx.file_registry.pop(expanded)
                    return entry["content"]
            except OSError:
                pass

        size = os.path.getsize(expanded)
        limit = int(ctx.cfg.get("read_file_limit", 100_000))

        if expanded.lower().endswith(".pdf"):
            try:
                from pypdf import PdfReader
                reader = PdfReader(expanded)
                content = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
            except ImportError:
                return "ERROR: 'pypdf' library is not installed. Please install it to read PDF files."
            except Exception as e:
                return f"ERROR reading PDF: {e}"
        else:
            with open(expanded, "r", encoding="utf-8") as f:
                content = f.read(limit)

        # For PDFs, we might have read the whole thing, so we apply the limit here too
        if len(content) > limit:
            content = content[:limit]
            truncated_kb = limit // 1024
            total_kb = size // 1024
            content += f"\n\n[…file truncated: showing first {truncated_kb}KB of {total_kb}KB]"
            ctx.console.print(f"  [yellow]⚠ read_file: {path} is {total_kb}KB, truncated to {truncated_kb}KB[/yellow]")
        elif size > limit and not expanded.lower().endswith(".pdf"):
            truncated_kb = limit // 1024
            total_kb = size // 1024
            content += f"\n\n[…file truncated: showing first {truncated_kb}KB of {total_kb}KB]"
            ctx.console.print(f"  [yellow]⚠ read_file: {path} is {total_kb}KB, truncated to {truncated_kb}KB[/yellow]")

        _cache_store(ctx, expanded, content)
        return content
    except Exception as e:
        return f"ERROR: {e}"


def write_file(path: str, content: str, ctx: AppContext) -> str:
    # If the model double-escaped newlines (literal \n with no real newlines), fix them.
    if "\n" not in content and "\\n" in content:
        content = content.replace("\\n", "\n").replace("\\t", "\t")
        ctx.console.print("  [yellow]⚠ Auto-converted literal \\\\n to newlines in file content[/yellow]")
    ctx.console.print(
        f"\n  [bold yellow]⚠ Write file:[/bold yellow] [cyan]{path}[/cyan] "
        f"[dim]({len(content)} characters)[/dim]"
    )
    if not ctx.auto_yes and not ctx.confirm("  Proceed? [y/N]: "):
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


def _is_build_command(command: str, ctx: AppContext) -> bool:
    keywords = ctx.cfg.get("build_filter_keywords", [])
    cmd_lower = command.lower()
    return any(kw in cmd_lower for kw in keywords)


def _filter_build_output(output: str, ctx: AppContext) -> str:
    """
    Filter build/compiler output to keep only significant lines.
    Linker error blocks (undefined reference, vtable for, etc.) are kept in full
    up to the next blank line so that adjacent symbol names are not lost.
    """
    lines = output.splitlines()
    total = len(lines)
    patterns = [re.compile(p, re.IGNORECASE) for p in ctx.cfg.get("build_filter_patterns", [])]
    context_n = int(ctx.cfg.get("build_filter_context_lines", 2))
    max_lines = int(ctx.cfg.get("build_output_max_lines", 120))

    # Build blank-line-separated block map so linker errors keep their full block
    blocks, block_start = [], None
    for idx, line in enumerate(lines):
        if line.strip():
            if block_start is None:
                block_start = idx
        elif block_start is not None:
            blocks.append((block_start, idx - 1))
            block_start = None
    if block_start is not None:
        blocks.append((block_start, total - 1))

    line_block = {}
    for start, end in blocks:
        for i in range(start, end + 1):
            line_block[i] = (start, end)

    keep = set()
    for idx, line in enumerate(lines):
        if _LINKER_RE.search(line):
            # Keep the entire blank-line-delimited block so symbol names on adjacent
            # lines (e.g. "In function `...'") are not lost
            if idx in line_block:
                bstart, bend = line_block[idx]
                keep.update(range(bstart, bend + 1))
            else:
                keep.add(idx)
        elif any(p.search(line) for p in patterns):
            keep.update(range(max(0, idx - context_n), min(total, idx + context_n + 1)))

    if not keep:
        return f"[Build output: {total} lines, no errors or warnings found.]"

    if len(keep) == total:
        # Nothing filtered — only enforce max_lines if needed
        if total <= max_lines:
            return output
        return (
            f"[Build output: showing first {max_lines}/{total} lines]\n"
            + "\n".join(lines[:max_lines])
            + f"\n[…{total - max_lines} more lines]"
        )

    result = []
    prev = None
    for idx in sorted(keep):
        if prev is not None and idx > prev + 1:
            result.append("[…]")
        result.append(lines[idx])
        prev = idx

    if len(result) > max_lines:
        result = result[:max_lines]
        result.append(f"[…truncated at {max_lines} lines; {total} total]")

    return f"[Build output: {len(result)}/{total} significant lines]\n" + "\n".join(result)


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

    venv_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin")
    env = os.environ.copy()
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = os.path.dirname(venv_bin)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=ctx.cfg["shell_timeout"],
            cwd=workdir,
            env=env,
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
        combined = "\n".join(parts) if parts else "(no output)"
        if (
            combined != "(no output)"
            and ctx.cfg.get("build_filter_enabled", True)
            and _is_build_command(command, ctx)
        ):
            combined = _filter_build_output(combined, ctx)
        return combined
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out ({ctx.cfg['shell_timeout']}s)"
    except Exception as e:
        return f"ERROR: {e}"


def patch_file(path: str, old_string: str, new_string: str, ctx: AppContext) -> str:
    ctx.console.print(
        f"\n  [bold yellow]⚠ Patch file:[/bold yellow] [cyan]{path}[/cyan]"
    )
    if not ctx.auto_yes and not ctx.confirm("  Proceed? [y/N]: "):
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


def glob_files(pattern: str, path: str = ".", ctx: AppContext = None) -> str:
    try:
        base = os.path.expanduser(path)
        full_pattern = os.path.join(base, pattern)
        matches = [m for m in glob.glob(full_pattern, recursive=True) if os.path.isfile(m)]
        if not matches:
            return "No files found."
        matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        if len(matches) > 200:
            remainder = len(matches) - 200
            return "\n".join(matches[:200]) + f"\n[…{remainder} more files truncated]"
        return "\n".join(matches)
    except Exception as e:
        return f"ERROR: {e}"


def list_known_files(ctx: AppContext) -> str:
    if not ctx.file_registry:
        return "No files have been read in this session."
    lines = [
        f"{path}  ({entry['size'] / 1024:.1f} KB)"
        for path, entry in ctx.file_registry.items()
    ]
    return "\n".join(lines)


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
        "glob_files": lambda a: glob_files(a["pattern"], a.get("path", "."), ctx),
        "list_known_files": lambda a: list_known_files(ctx),
    }
