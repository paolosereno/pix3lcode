import os
import json
import sys
from dataclasses import dataclass, field
from openai import OpenAI
from rich.console import Console

DEFAULTS: dict = {
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

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")


def load_config(extra_path: str | None = None, profile: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    for path in reversed(CONFIG_PATHS):  # home first, then local (overrides)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception as e:
                print(f"Warning: cannot read {path}: {e}")

    if extra_path:
        if os.path.exists(extra_path):
            try:
                with open(extra_path, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception as e:
                print(f"Error in config file: {e}")
        else:
            print(f"Config file not found: {extra_path}")

    if profile:
        profile_path = os.path.join(PROFILES_DIR, f"{profile}.json")
        if os.path.exists(profile_path):
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception as e:
                print(f"Error in profile '{profile}': {e}")
        else:
            print(f"Profile '{profile}' not found in {PROFILES_DIR}/")
            sys.exit(1)

    return cfg


@dataclass
class AppContext:
    cfg: dict
    model: str
    base_url: str
    auto_yes: bool
    profile: str | None
    client: OpenAI = field(init=False)
    console: Console = field(init=False)

    def __post_init__(self):
        self.client = OpenAI(base_url=self.base_url, api_key="lm-studio")
        self.console = Console()
