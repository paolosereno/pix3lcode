#!/usr/bin/env python3
import os
import sys
import re
import base64
import argparse
from datetime import datetime
from rich.markdown import Markdown
from rich.panel import Panel
from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory

from config import load_config, AppContext
from context import load_project_context, build_system_prompt
from session import save_session, load_session, pick_session, latest_session_id
from agent import agent_loop, compact_messages, check_context

# ── Vision helpers ────────────────────────────────────────────────────────────

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_MIME = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp", "bmp": "bmp"}


def _extract_image_paths(text: str) -> list[str]:
    candidates = re.findall(r'"([^"]+)"|\'([^\']+)\'|(\S+)', text)
    paths = []
    seen = set()
    for groups in candidates:
        for token in groups:
            if not token or token in seen:
                continue
            seen.add(token)
            ext = os.path.splitext(token)[1].lower()
            if ext in _IMAGE_EXTS:
                expanded = os.path.expanduser(token)
                if os.path.isfile(expanded):
                    paths.append(expanded)
    return paths


def _build_user_content(text: str, image_paths: list[str], console) -> "str | list":
    if not image_paths:
        return text
    content: list = [{"type": "text", "text": text}]
    for path in image_paths:
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = _MIME.get(ext, ext)
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}})
            console.print(f"  [dim]Image attached: {os.path.basename(path)}[/dim]")
        except Exception as e:
            console.print(f"  [yellow]Cannot attach {path}: {e}[/yellow]")
    return content


# ── CLI args ──────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Pix3lCode — LM Studio client")
parser.add_argument("--model", "-m", default=None, help="Model name to use")
parser.add_argument("--resume", "-r", nargs="?", const="last", metavar="ID",
                    help="Resume the last session or the one with the given ID")
parser.add_argument("--config", "-c", metavar="FILE", help="Path to an alternative config file")
parser.add_argument("--profile", "-p", metavar="NAME", help="Profile to use (file in profiles/<name>.json)")
parser.add_argument("--yes", "-y", action="store_true", help="Auto-confirm dangerous shell commands")
parser.add_argument("prompt_text", nargs="?", metavar="PROMPT", help="Non-interactive mode: run prompt and exit")
args = parser.parse_args()

# ── Config & context ──────────────────────────────────────────────────────────

cfg = load_config(extra_path=args.config, profile=args.profile)
model = args.model if args.model else cfg["model"]

ctx = AppContext(
    cfg=cfg,
    model=model,
    base_url=cfg["base_url"],
    auto_yes=args.yes,
    profile=args.profile,
)

# ── Non-interactive mode ──────────────────────────────────────────────────────

def run_once(user_input: str) -> None:
    """Run a single prompt and print the response to stdout."""
    messages = [
        {"role": "system", "content": build_system_prompt(ctx)},
        {"role": "user", "content": user_input},
    ]
    try:
        reply, _, _ = agent_loop(messages, ctx)
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

    messages: list = [{"role": "system", "content": build_system_prompt(ctx)}]
    resumed = False

    if args.resume:
        if args.resume == "last":
            loaded = pick_session(ctx)
        else:
            loaded = load_session(args.resume, ctx)
            if loaded is None:
                ctx.console.print(f"[red]Session '{args.resume}' not found.[/red]")
                loaded = None

        if loaded:
            messages = loaded
            if args.resume == "last":
                sid = latest_session_id(ctx)
                if sid:
                    session_id = sid
            else:
                session_id = args.resume
            resumed = True
            ctx.console.print(f"[dim]Session resumed: {session_id}[/dim]")

    ctx.console.print(
        Panel.fit(
            f"[bold cyan]Pix3lCode[/bold cyan] — LM Studio  [dim]{ctx.base_url}[/dim]\n"
            f"Model: [green]{ctx.model}[/green]"
            + (f"  profile: [magenta]{ctx.profile}[/magenta]" if ctx.profile else "")
            + (f"  [dim]session: {session_id}[/dim]" if resumed else "")
            + (f"\n[dim]Project context: CONTEXT.md loaded[/dim]" if load_project_context() else "") + "\n"
            "[dim]/help  |  /undo  |  /cd  |  /clear  |  /compact  |  /sessions  |  /exit  |  Ctrl+C[/dim]",
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
            save_session(messages, session_id, ctx)
            ctx.console.print(f"\n[dim]Session saved ({session_id}). Goodbye![/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/exit", "/quit"):
            save_session(messages, session_id, ctx)
            ctx.console.print(f"[dim]Session saved ({session_id}). Goodbye![/dim]")
            break

        if user_input.lower() == "/model":
            ctx.console.print(f"[bold]Model:[/bold] [green]{ctx.model}[/green]  [dim]{ctx.base_url}[/dim]")
            continue

        if user_input.lower() == "/tokens":
            total = total_prompt_tokens + total_completion_tokens
            ctx.console.print(
                f"[bold]Session tokens:[/bold]  "
                f"prompt [cyan]{total_prompt_tokens:,}[/cyan]  "
                f"completion [cyan]{total_completion_tokens:,}[/cyan]  "
                f"total [bold cyan]{total:,}[/bold cyan]"
            )
            continue

        if user_input.lower() == "/sessions":
            loaded = pick_session(ctx)
            if loaded:
                messages = loaded
                ctx.console.print("[dim]Session loaded.[/dim]")
            continue

        if user_input.lower() == "/help":
            ctx.console.print(Panel(
                "[bold]/help[/bold]      show this message\n"
                "[bold]/model[/bold]     show the active model and URL\n"
                "[bold]/tokens[/bold]    show token usage for the current session\n"
                "[bold]/sessions[/bold]  list saved sessions (number=resume, d<n>=delete)\n"
                "[bold]/undo[/bold]      remove the last user+assistant exchange from history\n"
                "[bold]/cd <path>[/bold] change working directory (affects file and shell tools)\n"
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
                f"[bold]Model:[/bold] [green]{ctx.model}[/green]  [dim]{ctx.base_url}[/dim]",
                title="[bold]Available commands[/bold]",
                border_style="cyan",
            ))
            continue

        if user_input.lower().startswith("/cd"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                ctx.console.print(f"[dim]Current directory: {os.getcwd()}[/dim]")
            else:
                target = os.path.expanduser(parts[1].strip())
                try:
                    os.chdir(target)
                    ctx.console.print(f"[dim]Working directory: {os.getcwd()}[/dim]")
                except Exception as e:
                    ctx.console.print(f"[red]Cannot change directory: {e}[/red]")
            continue

        if user_input.lower() == "/undo":
            non_system = [m for m in messages if (m["role"] if isinstance(m, dict) else m.role) != "system"]
            if len(non_system) < 2:
                ctx.console.print("[yellow]Nothing to undo.[/yellow]")
            else:
                # Remove messages from the end until we've removed the last user+assistant pair
                removed = 0
                while messages and removed < 2:
                    m = messages[-1]
                    role = m["role"] if isinstance(m, dict) else m.role
                    if role in ("user", "assistant", "tool"):
                        messages.pop()
                        if role in ("user", "assistant"):
                            removed += 1
                    else:
                        break
                ctx.console.print("[dim]Last exchange removed.[/dim]")
            continue

        if user_input.lower() == "/clear":
            messages = [{"role": "system", "content": build_system_prompt(ctx)}]
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            ctx.console.print("[dim]History cleared. New session started.[/dim]")
            continue

        if user_input.lower() == "/compact":
            with ctx.console.status("[bold blue]Compacting…[/bold blue]", spinner="dots") as s:
                ctx._live_status = s
                try:
                    messages = compact_messages(messages, ctx)
                except KeyboardInterrupt:
                    ctx.console.print("\n[yellow]Cancelled.[/yellow]")
                except Exception as e:
                    ctx.console.print(f"[red]Error during /compact: {e}[/red]")
                finally:
                    ctx._live_status = None
            continue

        if user_input.lower() == "/init":
            context_path = os.path.join(os.getcwd(), "CONTEXT.md")
            if os.path.exists(context_path):
                try:
                    answer = prompt("  CONTEXT.md already exists. Overwrite? [y/N]: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    answer = "n"
                if answer not in ("y", "yes"):
                    ctx.console.print("[dim]Operation cancelled.[/dim]")
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
            with ctx.console.status("[bold blue]Analyzing project…[/bold blue]", spinner="dots") as s:
                ctx._live_status = s
                try:
                    reply, prompt_tok, completion_tok = agent_loop(messages, ctx)
                except KeyboardInterrupt:
                    ctx.console.print("\n[yellow]Cancelled.[/yellow]")
                    messages.pop()
                    continue
                except Exception as e:
                    ctx.console.print(f"[red]Error during /init: {e}[/red]")
                    messages.pop()
                    continue
                finally:
                    ctx._live_status = None
            total_prompt_tokens += prompt_tok
            total_completion_tokens += completion_tok
            ctx.console.print("\n[bold blue]Assistant:[/bold blue]")
            ctx.console.print(Markdown(reply))
            if os.path.exists(context_path):
                ctx.console.print(f"[bold green]CONTEXT.md generated.[/bold green] It will be loaded automatically in future sessions.")
            save_session(messages, session_id, ctx)
            continue

        image_paths = _extract_image_paths(user_input)
        user_content = _build_user_content(user_input, image_paths, ctx.console)
        messages.append({"role": "user", "content": user_content})

        with ctx.console.status("[bold blue]Thinking…[/bold blue]", spinner="dots") as s:
            ctx._live_status = s
            try:
                reply, prompt_tok, completion_tok = agent_loop(messages, ctx)
            except KeyboardInterrupt:
                ctx.console.print("\n[yellow]Cancelled.[/yellow]")
                messages.pop()
                continue
            except Exception as e:
                ctx.console.print(f"[red]API error: {e}[/red]")
                messages.pop()
                continue
            finally:
                ctx._live_status = None

        total_prompt_tokens += prompt_tok
        total_completion_tokens += completion_tok
        total_tok = total_prompt_tokens + total_completion_tokens

        ctx.console.print("\n[bold blue]Assistant:[/bold blue]")
        ctx.console.print(Markdown(reply))
        check_context(total_prompt_tokens, ctx)
        ctx.console.print(
            f"  [dim]tokens: prompt {prompt_tok:,} | completion {completion_tok:,} | "
            f"session {total_tok:,}[/dim]"
        )

        # auto-save after each exchange
        save_session(messages, session_id, ctx)


if __name__ == "__main__":
    main()
