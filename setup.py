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
    print("Error: missing dependencies. Run: .venv/bin/pip install -r requirements.txt")
    sys.exit(1)

console = Console()

CONFIG_PATH_LOCAL = os.path.join(os.getcwd(), "pix3lcode_config.json")
CONFIG_PATH_HOME  = os.path.expanduser("~/.pix3lcode_config.json")

DEFAULTS = {
    "base_url": "http://10.5.0.2:1234/v1",
    "model": "",
    "sessions_dir": "~/.pix3lcode_sessions",
    "shell_timeout": 60,
    "api_timeout": 120,
    "api_retries": 3,
    "context_limit": 80000,
    "context_warn_threshold": 0.70,
    "max_tool_iterations": 20,
    "system_prompt": (
        "You are an AI assistant expert in programming and Linux systems. "
        "You have access to tools to read/write files, execute shell commands, and search code. "
        "Use these tools when needed. Before executing destructive commands, warn the user."
    ),
}


def ask(label: str, default: str | int | float) -> str:
    shown = str(default) if default != "" else ""
    suffix = f" [{shown}]" if shown else ""
    try:
        val = pt_prompt(f"  {label}{suffix}: ").strip()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Setup cancelled.[/dim]")
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
        console.print(f"  [yellow]Cannot fetch models: {e}[/yellow]")
        return []


def pick_model(models: list[str]) -> str:
    if not models:
        return ""

    table = Table(border_style="cyan", show_header=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Model", style="green")
    for i, m in enumerate(models, 1):
        table.add_row(str(i), m)
    console.print(table)

    try:
        choice = pt_prompt("  Choose model (number or name): ").strip()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Setup cancelled.[/dim]")
        sys.exit(0)

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            return models[idx]
        console.print("[red]Invalid number, enter the name manually.[/red]")
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
        "[bold cyan]Pix3lCode — Setup[/bold cyan]\n"
        "[dim]Configure the tool based on your LM Studio model and context[/dim]",
        border_style="cyan",
    ))

    # destination
    console.print("\n[bold]Where to save the configuration?[/bold]")
    console.print(f"  1  Current project  [dim]{CONFIG_PATH_LOCAL}[/dim]")
    console.print(f"  2  Home (global)    [dim]{CONFIG_PATH_HOME}[/dim]")
    dest_choice = ask("Choice", "1")
    config_path = CONFIG_PATH_LOCAL if dest_choice != "2" else CONFIG_PATH_HOME

    existing = load_existing(config_path)
    cfg = {**DEFAULTS, **existing}

    # API endpoint
    console.print("\n[bold]API endpoint[/bold]")
    console.print("  [dim]LM Studio: http://10.5.0.2:1234/v1  |  OpenRouter: https://openrouter.ai/api/v1[/dim]")
    cfg["base_url"] = ask("API URL", cfg["base_url"])
    cfg["api_key"] = ask("API key (lm-studio for LM Studio, sk-or-... for OpenRouter)", cfg.get("api_key", "lm-studio"))

    # fetch models
    console.print(f"\n  [dim]Fetching models from {cfg['base_url']}…[/dim]")
    models = fetch_models(cfg["base_url"])

    console.print("\n[bold]Model[/bold]")
    if models:
        console.print(f"  Found [green]{len(models)}[/green] models loaded in LM Studio:\n")
        selected = pick_model(models)
        if selected:
            cfg["model"] = selected
        else:
            cfg["model"] = ask("Model name", cfg["model"])
    else:
        cfg["model"] = ask("Model name", cfg["model"])

    # context
    console.print("\n[bold]Context[/bold]")
    console.print("  [dim]Enter the maximum token count you can load in LM Studio for this model.[/dim]")
    cfg["context_limit"] = int(ask("Context tokens", cfg["context_limit"]))

    raw_threshold = ask("Context warning threshold (e.g. 70 for 70%)", int(float(cfg["context_warn_threshold"]) * 100))
    cfg["context_warn_threshold"] = round(int(raw_threshold) / 100, 2)

    # timeouts and retry
    console.print("\n[bold]Timeouts and retry[/bold]")
    cfg["api_timeout"]        = int(ask("API timeout in seconds", cfg["api_timeout"]))
    cfg["shell_timeout"]      = int(ask("Shell command timeout in seconds", cfg["shell_timeout"]))
    cfg["api_retries"]        = int(ask("Retry attempts on API failure", cfg["api_retries"]))
    cfg["max_tool_iterations"] = int(ask("Max tool calls per response", cfg["max_tool_iterations"]))
    cfg["read_file_limit"]    = int(ask("Max bytes to read from a file (0 = unlimited)", cfg.get("read_file_limit", 100_000)))

    # confirmations
    console.print("\n[bold]Confirmations[/bold]")
    console.print("  [dim]auto_yes skips confirmation for write_file, patch_file and dangerous shell commands.[/dim]")
    auto_yes_val = ask("Skip all confirmations? (y/N)", "Y" if cfg.get("auto_yes") else "N")
    cfg["auto_yes"] = auto_yes_val.lower() in ("y", "yes")

    # sessions
    console.print("\n[bold]Sessions[/bold]")
    cfg["sessions_dir"] = ask("Sessions directory", cfg["sessions_dir"])

    # system prompt
    console.print("\n[bold]System prompt[/bold]")
    console.print(f"  [dim]Current: {cfg['system_prompt'][:80]}…[/dim]")
    change = ask("Edit system prompt? (y/N)", "N")
    if change.lower() in ("y", "yes"):
        console.print("  [dim]Enter the new system prompt (Enter to confirm):[/dim]")
        try:
            new_prompt = pt_prompt("  > ").strip()
            if new_prompt:
                cfg["system_prompt"] = new_prompt
        except (KeyboardInterrupt, EOFError):
            pass

    # save
    console.print(f"\n[dim]Saving to {config_path}…[/dim]")
    os.makedirs(os.path.dirname(config_path) if os.path.dirname(config_path) else ".", exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    console.print(Panel(
        f"[bold green]Configuration saved![/bold green]\n\n"
        f"  Model:      [green]{cfg['model']}[/green]\n"
        f"  URL:        [dim]{cfg['base_url']}[/dim]\n"
        f"  API key:    [dim]{'*' * 6 + cfg['api_key'][-4:] if len(cfg.get('api_key','')) > 6 else cfg.get('api_key','lm-studio')}[/dim]\n"
        f"  Context:    [cyan]{cfg['context_limit']:,}[/cyan] tokens "
        f"(warn at [cyan]{int(cfg['context_warn_threshold']*100)}%[/cyan])\n"
        f"  API:        timeout {cfg['api_timeout']}s, retry {cfg['api_retries']}x\n"
        f"  Max tools:  {cfg['max_tool_iterations']} iterations per response\n"
        f"  Read limit: {cfg['read_file_limit'] // 1024}KB per file\n"
        f"  Auto-yes:   {'yes (no confirmations)' if cfg.get('auto_yes') else 'no (ask before writing)'}\n"
        f"  Sessions:   [dim]{cfg['sessions_dir']}[/dim]\n\n"
        f"Start the tool with: [bold]./pix3lcode.sh[/bold]",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
