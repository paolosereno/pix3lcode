import os
from config import AppContext


def load_project_context() -> str | None:
    """Read CONTEXT.md from the current directory if it exists."""
    path = os.path.join(os.getcwd(), "CONTEXT.md")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return None


def build_system_prompt(ctx: AppContext) -> str:
    base = ctx.cfg["system_prompt"]
    project_ctx = load_project_context()
    if not project_ctx:
        return base
    return base + "\n\n## Project context\n\n" + project_ctx
