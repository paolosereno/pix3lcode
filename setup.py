#!/usr/bin/env python3
import json
import os
import sys

try:
    import httpx
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from prompt_toolkit import prompt as pt_prompt
except ImportError:
    print("Errore: dipendenze mancanti. Esegui: .venv/bin/pip install -r requirements.txt")
    sys.exit(1)

console = Console()

CONFIG_PATH_LOCAL = os.path.join(os.getcwd(), "llm_cli_config.json")
CONFIG_PATH_HOME  = os.path.expanduser("~/.llm_cli_config.json")

DEFAULTS = {
    "base_url": "http://10.5.0.2:1234/v1",
    "model": "",
    "sessions_dir": "~/.llm_cli_sessions",
    "shell_timeout": 60,
    "api_timeout": 120,
    "api_retries": 3,
    "context_limit": 80000,
    "context_warn_threshold": 0.70,
    "system_prompt": (
        "Sei un assistente AI esperto in programmazione e sistemi Linux. "
        "Hai accesso a strumenti per leggere/scrivere file, eseguire comandi shell e cercare nel codice. "
        "Usa questi strumenti quando necessario. Prima di eseguire comandi distruttivi, avvisa l'utente."
    ),
}


def ask(label: str, default: str | int | float) -> str:
    shown = str(default) if default != "" else ""
    suffix = f" [{shown}]" if shown else ""
    try:
        val = pt_prompt(f"  {label}{suffix}: ").strip()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Setup annullato.[/dim]")
        sys.exit(0)
    return val if val else str(default)


def fetch_models(base_url: str) -> list[str]:
    url = base_url.rstrip("/") + "/models"
    try:
        r = httpx.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()
        return [m["id"] for m in data.get("data", [])]
    except Exception as e:
        console.print(f"  [yellow]Impossibile recuperare i modelli: {e}[/yellow]")
        return []


def pick_model(models: list[str]) -> str:
    if not models:
        return ""

    table = Table(border_style="cyan", show_header=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Modello", style="green")
    for i, m in enumerate(models, 1):
        table.add_row(str(i), m)
    console.print(table)

    try:
        choice = pt_prompt("  Scegli modello (numero o nome): ").strip()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Setup annullato.[/dim]")
        sys.exit(0)

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            return models[idx]
        console.print("[red]Numero non valido, inserisci il nome manualmente.[/red]")
        return ""
    return choice


def load_existing(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def main():
    console.print(Panel.fit(
        "[bold cyan]LLM CLI — Setup[/bold cyan]\n"
        "[dim]Configura il tool in base al modello e al contesto di LM Studio[/dim]",
        border_style="cyan",
    ))

    # destinazione
    console.print("\n[bold]Dove salvare la configurazione?[/bold]")
    console.print(f"  1  Progetto corrente  [dim]{CONFIG_PATH_LOCAL}[/dim]")
    console.print(f"  2  Home (globale)     [dim]{CONFIG_PATH_HOME}[/dim]")
    dest_choice = ask("Scelta", "1")
    config_path = CONFIG_PATH_LOCAL if dest_choice != "2" else CONFIG_PATH_HOME

    existing = load_existing(config_path)
    cfg = {**DEFAULTS, **existing}

    # URL LM Studio
    console.print("\n[bold]LM Studio[/bold]")
    cfg["base_url"] = ask("Indirizzo API", cfg["base_url"])

    # recupera modelli
    console.print(f"\n  [dim]Recupero modelli da {cfg['base_url']}…[/dim]")
    models = fetch_models(cfg["base_url"])

    console.print("\n[bold]Modello[/bold]")
    if models:
        console.print(f"  Trovati [green]{len(models)}[/green] modelli caricati in LM Studio:\n")
        selected = pick_model(models)
        if selected:
            cfg["model"] = selected
        else:
            cfg["model"] = ask("Nome modello", cfg["model"])
    else:
        cfg["model"] = ask("Nome modello", cfg["model"])

    # contesto
    console.print("\n[bold]Contesto[/bold]")
    console.print("  [dim]Inserisci il numero di token massimo che riesci a caricare in LM Studio per questo modello.[/dim]")
    cfg["context_limit"] = int(ask("Token di contesto", cfg["context_limit"]))

    raw_threshold = ask("Soglia avviso contesto (es. 70 per 70%)", int(float(cfg["context_warn_threshold"]) * 100))
    cfg["context_warn_threshold"] = round(int(raw_threshold) / 100, 2)

    # timeout e retry
    console.print("\n[bold]Timeout e retry[/bold]")
    cfg["api_timeout"]  = int(ask("Timeout API in secondi", cfg["api_timeout"]))
    cfg["shell_timeout"] = int(ask("Timeout comandi shell in secondi", cfg["shell_timeout"]))
    cfg["api_retries"]  = int(ask("Tentativi retry in caso di errore", cfg["api_retries"]))

    # sessioni
    console.print("\n[bold]Sessioni[/bold]")
    cfg["sessions_dir"] = ask("Directory sessioni", cfg["sessions_dir"])

    # system prompt
    console.print("\n[bold]System prompt[/bold]")
    console.print(f"  [dim]Attuale: {cfg['system_prompt'][:80]}…[/dim]")
    change = ask("Modificare il system prompt? (s/N)", "N")
    if change.lower() in ("s", "si", "sì", "y", "yes"):
        console.print("  [dim]Inserisci il nuovo system prompt (Invio per terminare):[/dim]")
        try:
            new_prompt = pt_prompt("  > ").strip()
            if new_prompt:
                cfg["system_prompt"] = new_prompt
        except (KeyboardInterrupt, EOFError):
            pass

    # salva
    console.print(f"\n[dim]Salvataggio in {config_path}…[/dim]")
    os.makedirs(os.path.dirname(config_path) if os.path.dirname(config_path) else ".", exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    console.print(Panel(
        f"[bold green]Configurazione salvata![/bold green]\n\n"
        f"  Modello:   [green]{cfg['model']}[/green]\n"
        f"  URL:       [dim]{cfg['base_url']}[/dim]\n"
        f"  Contesto:  [cyan]{cfg['context_limit']:,}[/cyan] token "
        f"(avviso al [cyan]{int(cfg['context_warn_threshold']*100)}%[/cyan])\n"
        f"  API:       timeout {cfg['api_timeout']}s, retry {cfg['api_retries']}x\n"
        f"  Sessioni:  [dim]{cfg['sessions_dir']}[/dim]\n\n"
        f"Avvia il tool con: [bold]./llm.sh[/bold]",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
