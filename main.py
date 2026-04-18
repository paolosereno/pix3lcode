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
        "Sei un assistente AI esperto in programmazione e sistemi Linux. "
        "Hai accesso a strumenti per leggere/scrivere file, eseguire comandi shell e cercare nel codice. "
        "Usa questi strumenti quando necessario. Prima di eseguire comandi distruttivi, avvisa l'utente."
    ),
    "sessions_dir": "~/.llm_cli_sessions",
    "shell_timeout": 60,
    "api_timeout": 120,
    "api_retries": 3,
    "context_limit": 80000,
    "context_warn_threshold": 0.70,
}

CONFIG_PATHS = [
    os.path.join(os.getcwd(), "llm_cli_config.json"),
    os.path.expanduser("~/.llm_cli_config.json"),
]


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    for path in reversed(CONFIG_PATHS):  # home prima, poi locale (sovrascrive)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception as e:
                print(f"Attenzione: impossibile leggere {path}: {e}")
    return cfg


cfg = load_config()

SESSIONS_DIR = os.path.expanduser(cfg["sessions_dir"])

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")

parser = argparse.ArgumentParser(description="LLM CLI — LM Studio client")
parser.add_argument("--model", "-m", default=cfg["model"], help="Nome del modello da usare")
parser.add_argument("--resume", "-r", nargs="?", const="last", metavar="ID",
                    help="Riprende l'ultima sessione o quella con l'ID specificato")
parser.add_argument("--config", "-c", metavar="FILE", help="Percorso di un file di configurazione alternativo")
parser.add_argument("--profile", "-p", metavar="NOME", help="Profilo da usare (file in profiles/<nome>.json)")
parser.add_argument("--yes", "-y", action="store_true", help="Conferma automaticamente i comandi shell pericolosi")
parser.add_argument("prompt_text", nargs="?", metavar="PROMPT", help="Modalità non interattiva: esegue il prompt e termina")
args = parser.parse_args()

if args.config:
    if os.path.exists(args.config):
        try:
            with open(args.config, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"Errore nel file di configurazione: {e}")
    else:
        print(f"File di configurazione non trovato: {args.config}")

if args.profile:
    profile_path = os.path.join(PROFILES_DIR, f"{args.profile}.json")
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"Errore nel profilo '{args.profile}': {e}")
    else:
        print(f"Profilo '{args.profile}' non trovato in {PROFILES_DIR}/")
        sys.exit(1)

# --model da CLI sovrascrive il profilo solo se esplicitamente passato
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
            "description": "Legge il contenuto di un file dal filesystem",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Percorso del file da leggere"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Scrive o sovrascrive un file sul filesystem",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Percorso del file da scrivere"},
                    "content": {"type": "string", "description": "Contenuto da scrivere nel file"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Elenca i file e le cartelle in una directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Percorso della directory (default: directory corrente)",
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
            "description": "Esegue un comando shell Linux e restituisce stdout e stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Comando shell da eseguire"},
                    "workdir": {
                        "type": "string",
                        "description": "Directory di lavoro (opzionale, default: directory corrente)",
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
                "Modifica una parte specifica di un file sostituendo un testo esatto con un nuovo testo. "
                "Preferisci questo tool a write_file quando devi cambiare solo una porzione del file. "
                "Il testo da sostituire deve essere esatto e univoco nel file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Percorso del file da modificare"},
                    "old_string": {"type": "string", "description": "Testo esatto da sostituire (deve essere univoco nel file)"},
                    "new_string": {"type": "string", "description": "Nuovo testo che sostituirà old_string"},
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
                "Cerca un pattern di testo nei file di una directory (come grep). "
                "Restituisce le righe corrispondenti con il nome del file e il numero di riga. "
                "Usa questo tool per trovare funzioni, variabili o pattern nel codice senza leggere tutti i file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Pattern di ricerca (regex supportata)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory o file in cui cercare (default: directory corrente)",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Filtro sui file, es. '*.py', '*.js' (default: tutti i file)",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Ricerca case-sensitive (default: false)",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Numero di righe di contesto prima e dopo ogni match (default: 0)",
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
        return f"ERRORE: {e}"


def _write_file(path: str, content: str) -> str:
    try:
        expanded = os.path.expanduser(path)
        parent = os.path.dirname(expanded)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(expanded, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File scritto con successo: {path} ({len(content)} caratteri)"
    except Exception as e:
        return f"ERRORE: {e}"


def _list_directory(path: str = ".") -> str:
    try:
        expanded = os.path.expanduser(path)
        entries = sorted(os.listdir(expanded))
        lines = []
        for e in entries:
            full = os.path.join(expanded, e)
            tag = "/" if os.path.isdir(full) else ""
            lines.append(f"{e}{tag}")
        return "\n".join(lines) if lines else "(vuota)"
    except Exception as e:
        return f"ERRORE: {e}"


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
            console.print(f"\n  [bold yellow]⚠ Comando pericoloso eseguito (--yes):[/bold yellow] [yellow]{command}[/yellow]")
        else:
            console.print(
                f"\n  [bold red]⚠ Comando potenzialmente pericoloso:[/bold red]\n"
                f"  [yellow]{command}[/yellow]"
            )
            try:
                answer = prompt("  Eseguire? [s/N]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                answer = "n"
            if answer not in ("s", "si", "sì", "y", "yes"):
                return "Esecuzione annullata dall'utente."

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
        return "\n".join(parts) if parts else "(nessun output)"
    except subprocess.TimeoutExpired:
        return "ERRORE: comando scaduto (timeout 60s)"
    except Exception as e:
        return f"ERRORE: {e}"


def _patch_file(path: str, old_string: str, new_string: str) -> str:
    try:
        expanded = os.path.expanduser(path)
        with open(expanded, "r", encoding="utf-8") as f:
            content = f.read()
        if old_string not in content:
            return f"ERRORE: testo non trovato nel file '{path}'. Verifica che il testo da sostituire sia esatto."
        count = content.count(old_string)
        if count > 1:
            return f"ERRORE: il testo da sostituire appare {count} volte nel file. Fornisci più contesto per renderlo univoco."
        new_content = content.replace(old_string, new_string, 1)
        with open(expanded, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"File modificato con successo: {path}"
    except FileNotFoundError:
        return f"ERRORE: file non trovato '{path}'"
    except Exception as e:
        return f"ERRORE: {e}"


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
            return "Nessun risultato trovato."
        lines = out.splitlines()
        if len(lines) > 200:
            return "\n".join(lines[:200]) + f"\n[…{len(lines) - 200} righe troncate]"
        return out
    except subprocess.TimeoutExpired:
        return "ERRORE: ricerca scaduta (timeout 30s)"
    except Exception as e:
        return f"ERRORE: {e}"


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
}


def run_tool(name: str, args: dict) -> str:
    handler = TOOL_DISPATCH.get(name)
    if handler is None:
        return f"Tool sconosciuto: {name}"
    return handler(args)


def _api_call_with_retry(messages: list) -> object:
    """Chiama l'API con retry automatico in caso di errore."""
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
            last_exc = e
            if attempt < retries:
                wait = 2 ** attempt  # backoff esponenziale: 2s, 4s, 8s…
                console.print(f"  [yellow]Tentativo {attempt}/{retries} fallito ({e}). Riprovo tra {wait}s…[/yellow]")
                time.sleep(wait)
    raise last_exc


def _check_context(total_prompt_tokens: int) -> None:
    """Avvisa se i token usati superano la soglia configurata."""
    limit = int(cfg["context_limit"])
    threshold = float(cfg["context_warn_threshold"])
    if limit <= 0:
        return
    usage_ratio = total_prompt_tokens / limit
    if usage_ratio >= 1.0:
        console.print(
            f"  [bold red]⚠ Contesto esaurito![/bold red] "
            f"[red]{total_prompt_tokens:,} / {limit:,} token. Usa /compact o /clear.[/red]"
        )
    elif usage_ratio >= threshold:
        pct = int(usage_ratio * 100)
        console.print(
            f"  [bold yellow]⚠ Contesto al {pct}%[/bold yellow] "
            f"[yellow]({total_prompt_tokens:,} / {limit:,} token). "
            f"Considera /compact per liberare spazio.[/yellow]"
        )


def agent_loop(messages: list) -> tuple[str, int, int]:
    """Ritorna (risposta, prompt_tokens_totali, completion_tokens_totali)."""
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

            preview = result if len(result) <= 300 else result[:300] + "\n[…troncato]"
            console.print(f"  [dim]{preview}[/dim]")

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


def compact_messages(messages: list) -> list:
    system = messages[0]
    conversation = messages[1:]
    if not conversation:
        console.print("[dim]Nessuna conversazione da compattare.[/dim]")
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
                "Riassumi la conversazione seguente in modo conciso, "
                "mantenendo tutti i dettagli tecnici importanti, "
                "le decisioni prese, i file modificati e il contesto del progetto. "
                "Il riassunto sarà usato come punto di partenza per continuare il lavoro.\n\n"
                + "\n\n".join(history_text)
            ),
        },
    ]

    console.print("[dim]Compattando la conversazione…[/dim]")
    response = client.chat.completions.create(model=MODEL, messages=summary_prompt)
    summary = response.choices[0].message.content or ""

    new_messages = [
        system,
        {"role": "assistant", "content": f"[Riassunto della conversazione precedente]\n\n{summary}"},
    ]
    console.print(Panel(Markdown(summary), title="[bold]Riassunto[/bold]", border_style="dim"))
    return new_messages


# ── Gestione sessioni ─────────────────────────────────────────────────────────

def _serialize_messages(messages: list) -> list:
    """Converte i messaggi in dict semplici (gestisce oggetti pydantic dell'SDK)."""
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
    return "sessione vuota"


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


def pick_session() -> list | None:
    """Mostra le ultime sessioni e chiede all'utente quale riprendere."""
    sessions = list_sessions()
    if not sessions:
        console.print("[dim]Nessuna sessione salvata.[/dim]")
        return None

    table = Table(title="Sessioni recenti", border_style="cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Data", style="dim")
    table.add_column("Modello", style="green")
    table.add_column("Anteprima")

    for i, s in enumerate(sessions, 1):
        saved_at = s.get("saved_at", "")[:16].replace("T", " ")
        table.add_row(str(i), s["id"], saved_at, s.get("model", "?"), s.get("preview", ""))

    console.print(table)

    try:
        choice = prompt("Scegli sessione (numero o ID, Invio per annullare): ").strip()
    except (KeyboardInterrupt, EOFError):
        return None

    if not choice:
        return None

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(sessions):
            return load_session(sessions[idx]["id"])
        console.print("[red]Numero non valido.[/red]")
        return None

    return load_session(choice)


# ── Contesto di progetto ──────────────────────────────────────────────────────

def load_project_context() -> str | None:
    """Legge CONTEXT.md dalla directory corrente se esiste."""
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
        + "\n\n## Contesto del progetto\n\n"
        + context
    )


# ── Modalità non interattiva ──────────────────────────────────────────────────

def run_once(user_input: str) -> None:
    """Esegue un singolo prompt e stampa la risposta su stdout."""
    system_prompt = build_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    try:
        reply, _, _ = agent_loop(messages)
        print(reply)
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # modalità non interattiva
    if args.prompt_text:
        run_once(args.prompt_text)
        return

    # leggi da stdin se c'è pipe (es. cat file.py | ./llm.sh "spiega questo")
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
                console.print(f"[red]Sessione '{args.resume}' non trovata.[/red]")

        if loaded:
            messages = loaded
            # riusa l'ID della sessione ripresa per sovrascriverla al salvataggio
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
            console.print(f"[dim]Sessione ripresa: {session_id}[/dim]")

    console.print(
        Panel.fit(
            f"[bold cyan]LLM CLI[/bold cyan] — LM Studio  [dim]{BASE_URL}[/dim]\n"
            f"Modello: [green]{MODEL}[/green]"
            + (f"  profilo: [magenta]{args.profile}[/magenta]" if args.profile else "")
            + (f"  [dim]sessione: {session_id}[/dim]" if resumed else "")
            + (f"\n[dim]Contesto progetto: CONTEXT.md caricato[/dim]" if load_project_context() else "") + "\n"
            "[dim]/help  |  /clear  |  /compact  |  /sessions  |  /exit  |  Ctrl+C[/dim]",
            border_style="cyan",
        )
    )

    history_file = os.path.expanduser("~/.llm_cli_history")
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
            console.print(f"\n[dim]Sessione salvata ({session_id}). Arrivederci![/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/exit", "/quit"):
            save_session(messages, session_id)
            console.print(f"[dim]Sessione salvata ({session_id}). Arrivederci![/dim]")
            break

        if user_input.lower() == "/model":
            console.print(f"[bold]Modello:[/bold] [green]{MODEL}[/green]  [dim]{BASE_URL}[/dim]")
            continue

        if user_input.lower() == "/tokens":
            total = total_prompt_tokens + total_completion_tokens
            console.print(
                f"[bold]Token sessione:[/bold]  "
                f"prompt [cyan]{total_prompt_tokens:,}[/cyan]  "
                f"completion [cyan]{total_completion_tokens:,}[/cyan]  "
                f"totale [bold cyan]{total:,}[/bold cyan]"
            )
            continue

        if user_input.lower() == "/sessions":
            loaded = pick_session()
            if loaded:
                messages = loaded
                console.print("[dim]Sessione caricata.[/dim]")
            continue

        if user_input.lower() == "/help":
            console.print(Panel(
                "[bold]/help[/bold]      mostra questo messaggio\n"
                "[bold]/model[/bold]     mostra il modello e l'URL in uso\n"
                "[bold]/tokens[/bold]    mostra i token usati nella sessione corrente\n"
                "[bold]/sessions[/bold]  mostra le sessioni salvate e permette di riprenderne una\n"
                "[bold]/clear[/bold]     cancella la cronologia e riparte da zero\n"
                "[bold]/compact[/bold]   riassume la conversazione per liberare contesto\n"
                "[bold]/init[/bold]      analizza il progetto e genera CONTEXT.md\n"
                "[bold]/exit[/bold]      salva ed esce\n\n"
                "[bold cyan]Tool disponibili per il modello:[/bold cyan]\n"
                "  [cyan]read_file[/cyan]      legge un file\n"
                "  [cyan]write_file[/cyan]     scrive o crea un file\n"
                "  [cyan]patch_file[/cyan]     modifica solo una parte di un file (old→new)\n"
                "  [cyan]list_directory[/cyan] elenca i file di una directory\n"
                "  [cyan]execute_shell[/cyan]  esegue un comando shell (chiede conferma se pericoloso)\n"
                "  [cyan]search_files[/cyan]   cerca testo nei file con regex (come grep)\n\n"
                "[bold cyan]Resume da riga di comando:[/bold cyan]\n"
                "  [dim]./llm.sh --resume[/dim]          riprende scegliendo dalla lista\n"
                "  [dim]./llm.sh --resume 20240418_1230[/dim]  riprende una sessione specifica\n\n"
                f"[bold]Modello:[/bold] [green]{MODEL}[/green]  [dim]{BASE_URL}[/dim]",
                title="[bold]Comandi disponibili[/bold]",
                border_style="cyan",
            ))
            continue

        if user_input.lower() == "/clear":
            messages = [{"role": "system", "content": build_system_prompt()}]
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            console.print("[dim]Cronologia cancellata. Nuova sessione avviata.[/dim]")
            continue

        if user_input.lower() == "/compact":
            with console.status("[bold blue]Compattando…[/bold blue]", spinner="dots"):
                try:
                    messages = compact_messages(messages)
                except Exception as e:
                    console.print(f"[red]Errore durante /compact: {e}[/red]")
            continue

        if user_input.lower() == "/init":
            context_path = os.path.join(os.getcwd(), "CONTEXT.md")
            if os.path.exists(context_path):
                try:
                    answer = prompt("  CONTEXT.md esiste già. Sovrascrivere? [s/N]: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    answer = "n"
                if answer not in ("s", "si", "sì", "y", "yes"):
                    console.print("[dim]Operazione annullata.[/dim]")
                    continue

            init_prompt = (
                f"Analizza il progetto nella directory '{os.getcwd()}'. "
                "Usa list_directory e read_file per esplorare la struttura, "
                "leggere i file principali (README, file di configurazione, entry point, ecc.) "
                "e capire le tecnologie usate, le convenzioni e l'architettura. "
                "Poi scrivi un file CONTEXT.md conciso (max 300 parole) con queste sezioni:\n"
                "- Nome e descrizione breve del progetto\n"
                "- Tecnologie e dipendenze principali\n"
                "- Struttura delle directory\n"
                "- Entry point e file principali\n"
                "- Convenzioni di codice (se rilevabili)\n\n"
                "Usa write_file per salvare il file CONTEXT.md nella directory corrente."
            )
            messages.append({"role": "user", "content": init_prompt})
            with console.status("[bold blue]Analisi del progetto in corso…[/bold blue]", spinner="dots"):
                try:
                    reply, prompt_tok, completion_tok = agent_loop(messages)
                except Exception as e:
                    console.print(f"[red]Errore durante /init: {e}[/red]")
                    messages.pop()
                    continue
            total_prompt_tokens += prompt_tok
            total_completion_tokens += completion_tok
            console.print("\n[bold blue]Assistant:[/bold blue]")
            console.print(Markdown(reply))
            if os.path.exists(context_path):
                console.print(f"[bold green]CONTEXT.md generato.[/bold green] Verrà caricato automaticamente nelle prossime sessioni.")
            save_session(messages, session_id)
            continue

        messages.append({"role": "user", "content": user_input})

        with console.status("[bold blue]Sto pensando…[/bold blue]", spinner="dots"):
            try:
                reply, prompt_tok, completion_tok = agent_loop(messages)
            except Exception as e:
                console.print(f"[red]Errore API: {e}[/red]")
                messages.pop()
                continue

        total_prompt_tokens += prompt_tok
        total_completion_tokens += completion_tok
        total_tok = total_prompt_tokens + total_completion_tokens

        console.print("\n[bold blue]Assistant:[/bold blue]")
        console.print(Markdown(reply))
        _check_context(total_prompt_tokens)
        console.print(
            f"  [dim]token: prompt {prompt_tok:,} | completion {completion_tok:,} | "
            f"sessione {total_tok:,}[/dim]"
        )

        # auto-save dopo ogni scambio
        save_session(messages, session_id)


if __name__ == "__main__":
    main()
