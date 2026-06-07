import os
import json
import sys
from dataclasses import dataclass, field
from openai import OpenAI
from rich.console import Console
from prompt_toolkit import prompt as pt_prompt

DEFAULTS: dict = {
    "base_url": "http://10.5.0.2:1234/v1",
    "api_key": "lm-studio",
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
    "max_tool_iterations": 20,
    "read_file_limit": 100_000,
    "auto_yes": False,
    "tool_result_evict_threshold": 1500,
    "build_filter_enabled": True,
    "build_filter_keywords": ["make", "qmake", "cmake", "ninja", "g++", "gcc", "clang++", "clang", "msbuild", "cargo"],
    "build_filter_patterns": ["error:", "warning:", "undefined reference", "vtable for", "note:", "ld:", "cannot find -l", "DSO missing"],
    "build_filter_context_lines": 2,
    "build_output_max_lines": 120,
    "file_cache_max_files": 50,
    "file_cache_max_bytes": 10_000_000,
    "agent_context_limit_threshold": 0.95,
    "stagnation_threshold": 3,
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
    no_tools: bool = False
    client: OpenAI = field(init=False)
    console: Console = field(init=False)

    def __post_init__(self):
        self.auto_yes = self.auto_yes or bool(self.cfg.get("auto_yes", False))
        self.client = OpenAI(base_url=self.base_url, api_key=self.cfg.get("api_key", "lm-studio"))
        self.console = Console()
        self._live_status = None  # set by main loop when spinner is active
        self.file_registry: dict = {}  # {abs_path: {mtime, size, content}} — LRU cache

    def confirm(self, question: str) -> bool:
        """Stop the spinner, ask a yes/no question, restart the spinner."""
        if self._live_status:
            self._live_status.stop()
        try:
            answer = pt_prompt(question).strip().lower()
        except (KeyboardInterrupt, EOFError):
            answer = "n"
        finally:
            if self._live_status:
                self._live_status.start()
        return answer in ("y", "yes")
