import os
import json
import glob as glob_module
from datetime import datetime
from rich.table import Table
from prompt_toolkit import prompt
from config import AppContext


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


def save_session(messages: list, session_id: str, ctx: AppContext) -> None:
    sessions_dir = os.path.expanduser(ctx.cfg["sessions_dir"])
    os.makedirs(sessions_dir, exist_ok=True)
    path = os.path.join(sessions_dir, f"{session_id}.json")
    data = {
        "id": session_id,
        "model": ctx.model,
        "saved_at": datetime.now().isoformat(),
        "preview": _first_user_message(messages),
        "messages": _serialize_messages(messages),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_session(session_id: str, ctx: AppContext) -> list | None:
    sessions_dir = os.path.expanduser(ctx.cfg["sessions_dir"])
    path = os.path.join(sessions_dir, f"{session_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["messages"]


def list_sessions(ctx: AppContext, n: int = 10) -> list[dict]:
    sessions_dir = os.path.expanduser(ctx.cfg["sessions_dir"])
    files = sorted(
        glob_module.glob(os.path.join(sessions_dir, "*.json")),
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


def delete_session(session_id: str, ctx: AppContext) -> bool:
    sessions_dir = os.path.expanduser(ctx.cfg["sessions_dir"])
    path = os.path.join(sessions_dir, f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def _print_sessions_table(sessions: list, ctx: AppContext) -> None:
    table = Table(title="Recent sessions", border_style="cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Date", style="dim")
    table.add_column("Model", style="green")
    table.add_column("Preview")
    for i, s in enumerate(sessions, 1):
        saved_at = s.get("saved_at", "")[:16].replace("T", " ")
        table.add_row(str(i), s["id"], saved_at, s.get("model", "?"), s.get("preview", ""))
    ctx.console.print(table)


def pick_session(ctx: AppContext) -> list | None:
    """Show recent sessions and ask the user which one to resume or delete."""
    sessions = list_sessions(ctx)
    if not sessions:
        ctx.console.print("[dim]No saved sessions.[/dim]")
        return None

    while True:
        _print_sessions_table(sessions, ctx)
        ctx.console.print("[dim]Enter a number to resume, d<n> to delete (e.g. d1), Enter to cancel[/dim]")

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
                    delete_session(sid, ctx)
                    ctx.console.print(f"[dim]Session {sid} deleted.[/dim]")
                    sessions = list_sessions(ctx)
                    if not sessions:
                        ctx.console.print("[dim]No sessions left.[/dim]")
                        return None
                    continue
            ctx.console.print("[red]Invalid number.[/red]")
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                return load_session(sessions[idx]["id"], ctx)
            ctx.console.print("[red]Invalid number.[/red]")
            continue

        return load_session(choice, ctx)


def latest_session_id(ctx: AppContext) -> str | None:
    sessions_dir = os.path.expanduser(ctx.cfg["sessions_dir"])
    files = sorted(
        glob_module.glob(os.path.join(sessions_dir, "*.json")),
        key=os.path.getmtime,
        reverse=True,
    )
    if files:
        return os.path.splitext(os.path.basename(files[0]))[0]
    return None
