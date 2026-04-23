import json
import time
import sys
from types import SimpleNamespace
from rich.markdown import Markdown
from rich.panel import Panel
from config import AppContext
import tools as tools_module
import git_tools


def _build_tools_list(ctx: AppContext) -> list:
    if ctx.no_tools:
        return []
    return tools_module.TOOL_DEFINITIONS + git_tools.TOOL_DEFINITIONS


def _build_dispatch(ctx: AppContext) -> dict:
    dispatch = tools_module.make_dispatch(ctx)
    dispatch.update(git_tools.make_dispatch(ctx))
    return dispatch


def run_tool(name: str, tool_args: dict, dispatch: dict) -> str:
    handler = dispatch.get(name)
    if handler is None:
        return f"Unknown tool: {name}"
    return handler(tool_args)


def _has_user_message(messages: list) -> bool:
    return any(
        (m["role"] if isinstance(m, dict) else m.role) == "user"
        for m in messages
    )


def _stream_api_call(
    messages: list, tools_list: list, ctx: AppContext, text_callback=None
) -> tuple:
    """
    Streaming API call.
    Calls text_callback(None) once before the first text chunk (start signal),
    then text_callback(chunk) for each text chunk.
    Returns (content, tool_calls, prompt_tokens, completion_tokens).
    tool_calls is None if the response has no tool calls.
    """
    retries = int(ctx.cfg["api_retries"])
    timeout = int(ctx.cfg["api_timeout"])
    last_exc = None
    stream = None

    for attempt in range(1, retries + 1):
        try:
            kwargs = dict(
                model=ctx.model,
                messages=messages,
                timeout=timeout,
                stream=True,
                stream_options={"include_usage": True},
            )
            if tools_list:
                kwargs["tools"] = tools_list
                kwargs["tool_choice"] = "auto"
            stream = ctx.client.chat.completions.create(**kwargs)
            break
        except Exception as e:
            err_str = str(e)
            if "No user query found" in err_str and not _has_user_message(messages):
                ctx.console.print(
                    "  [yellow]⚠ Model template requires a user message. "
                    "Adding one automatically.[/yellow]"
                )
                messages.insert(1, {"role": "user", "content": "Continue."})
                continue
            last_exc = e
            if attempt < retries:
                wait = 2 ** attempt
                ctx.console.print(
                    f"  [yellow]Attempt {attempt}/{retries} failed ({e}). Retrying in {wait}s…[/yellow]"
                )
                time.sleep(wait)

    if stream is None:
        raise last_exc

    content = ""
    tool_calls_raw = {}
    prompt_tokens = 0
    completion_tokens = 0
    streaming_started = False

    for chunk in stream:
        if hasattr(chunk, "usage") and chunk.usage:
            prompt_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0

        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta

        if delta.content:
            if not streaming_started:
                if text_callback:
                    text_callback(None)  # start signal
                streaming_started = True
            content += delta.content
            if text_callback:
                text_callback(delta.content)

        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls_raw:
                    tool_calls_raw[idx] = {"id": "", "name": "", "arguments": ""}
                if tc_delta.id:
                    tool_calls_raw[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tool_calls_raw[idx]["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        tool_calls_raw[idx]["arguments"] += tc_delta.function.arguments

    if tool_calls_raw:
        tool_calls = [
            SimpleNamespace(
                id=tool_calls_raw[idx]["id"],
                function=SimpleNamespace(
                    name=tool_calls_raw[idx]["name"],
                    arguments=tool_calls_raw[idx]["arguments"],
                ),
            )
            for idx in sorted(tool_calls_raw.keys())
        ]
    else:
        tool_calls = None

    return content, tool_calls, prompt_tokens, completion_tokens


def check_context(total_prompt_tokens: int, ctx: AppContext) -> None:
    limit = int(ctx.cfg["context_limit"])
    threshold = float(ctx.cfg["context_warn_threshold"])
    if limit <= 0:
        return
    usage_ratio = total_prompt_tokens / limit
    if usage_ratio >= 1.0:
        ctx.console.print(
            f"  [bold red]⚠ Context exhausted![/bold red] "
            f"[red]{total_prompt_tokens:,} / {limit:,} tokens. Use /compact or /clear.[/red]"
        )
    elif usage_ratio >= threshold:
        pct = int(usage_ratio * 100)
        ctx.console.print(
            f"  [bold yellow]⚠ Context at {pct}%[/bold yellow] "
            f"[yellow]({total_prompt_tokens:,} / {limit:,} tokens). "
            f"Consider /compact to free up space.[/yellow]"
        )


def agent_loop(
    messages: list, ctx: AppContext, text_callback=None
) -> tuple[str, int, int]:
    """Returns (reply, total_prompt_tokens, total_completion_tokens)."""
    tools_list = _build_tools_list(ctx)
    dispatch = _build_dispatch(ctx)
    total_prompt = 0
    total_completion = 0
    max_iterations = int(ctx.cfg.get("max_tool_iterations", 20))
    iteration = 0

    while True:
        content, tool_calls, prompt_tokens, completion_tokens = _stream_api_call(
            messages, tools_list, ctx, text_callback=text_callback
        )

        total_prompt += prompt_tokens
        total_completion += completion_tokens

        if not tool_calls:
            messages.append({"role": "assistant", "content": content})
            return content, total_prompt, total_completion

        iteration += 1
        if iteration >= max_iterations:
            ctx.console.print(
                f"  [bold red]⚠ Tool iteration limit reached ({max_iterations}). Stopping.[/bold red]"
            )
            content = content or f"[Stopped after {max_iterations} tool calls]"
            messages.append({"role": "assistant", "content": content})
            return content, total_prompt, total_completion

        messages.append({
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            ctx.console.print(f"\n  [bold yellow]⚙ Tool:[/bold yellow] [cyan]{name}[/cyan]  {tool_args}")
            result = run_tool(name, tool_args, dispatch)

            preview = result if len(result) <= 300 else result[:300] + "\n[…truncated]"
            ctx.console.print(f"  [dim]{preview}[/dim]")

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


def compact_messages(messages: list, ctx: AppContext) -> list:
    system = messages[0]
    conversation = messages[1:]
    if not conversation:
        ctx.console.print("[dim]Nothing to compact.[/dim]")
        return messages

    history_text = []
    for m in conversation:
        role = m["role"] if isinstance(m, dict) else m.role
        if role == "tool":
            continue
        content = m["content"] if isinstance(m, dict) else m.content
        if isinstance(content, list):
            text_parts = [p["text"] for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = " ".join(text_parts) + " [image]" * sum(
                1 for p in content if isinstance(p, dict) and p.get("type") == "image_url"
            )
        if content:
            history_text.append(f"{role.upper()}: {content}")

    summary_prompt = [
        system,
        {
            "role": "user",
            "content": (
                "Summarize the following conversation concisely, "
                "keeping all important technical details, "
                "decisions made, modified files and project context. "
                "The summary will be used as a starting point to continue the work.\n\n"
                + "\n\n".join(history_text)
            ),
        },
    ]

    ctx.console.print("[dim]Compacting conversation…[/dim]")
    response = ctx.client.chat.completions.create(model=ctx.model, messages=summary_prompt)
    summary = response.choices[0].message.content or ""

    new_messages = [
        system,
        {"role": "user", "content": "Continue from the summary of the previous conversation."},
        {"role": "assistant", "content": f"[Summary of previous conversation]\n\n{summary}"},
    ]
    ctx.console.print(Panel(Markdown(summary), title="[bold]Summary[/bold]", border_style="dim"))
    return new_messages
