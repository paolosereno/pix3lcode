# Pix3lCode — Improvements

## Bug / robustness

- [x] **`agent_loop` max iterations** — added `max_tool_iterations` (default 20) in config; loop stops with a warning if limit is reached.
- [ ] **`read_file` size limit** — reading a large file dumps everything into context. Add a configurable limit (e.g. 100KB) with truncation and warning.
- [x] **`import re` inside `_is_dangerous`** — moved to top of `tools.py`.
- [x] **`loaded` possibly undefined** — fixed in refactored `main.py`: `loaded` is always initialized to `None` before the resume branch.
- [x] **Spinner blocks confirmation prompt** — `ctx.confirm()` stops the Rich spinner before asking, restarts it after; fixes `execute_shell` and `git_commit` hanging silently.

## High priority

- [ ] **Response streaming** — text appears word by word instead of waiting for the full response. Most impactful UX improvement.
- [x] **Shell confirmation** — asks confirmation for dangerous commands (`rm`, `sudo`, `kill`, etc.)
- [x] **`patch_file` tool** — modifies only a portion of a file via old→new replacement
- [x] **Git tools** — `git_status`, `git_diff`, `git_log`, `git_commit` (with user confirmation)
- [x] **Ctrl+C cancels current operation** — instead of crashing the app

## Medium priority

- [ ] **`/undo`** — removes the last exchange (user + assistant) from history, useful when the response is wrong.
- [ ] **Confirmation for `write_file` and `patch_file`** — currently only `execute_shell` asks confirmation, but writing/patching files is equally invasive.
- [ ] **Multiline input** — `Alt+Enter` to send multi-line blocks (e.g. code snippets).
- [x] **`max_tool_iterations` in config** — exposed as config key, default 20.
- [x] **`search_files` tool** — search text in files with regex (like grep)
- [x] **Configurable system prompt** — editable via `pix3lcode_config.json` without touching the code
- [x] **Session delete in `/sessions`** — type `d<n>` to delete a session from the list

## Low priority

- [ ] **`/export`** — export the current session to a readable markdown file.
- [ ] **`/rename`** — rename the current session with a meaningful name instead of a timestamp.
- [ ] **`--no-tools` flag** — start without tools (pure chat, saves tokens in system prompt).
- [ ] **`/cd <path>`** — change working directory during the session without exiting.
- [x] **`/compact`** — summarize the conversation to free up context
- [x] **`/clear`** — clear history and start a new session
- [x] **`/help`** — show all available commands and tools
- [x] **`/model`** — show the active model and LM Studio URL
- [x] **Session save** — auto-save after each exchange, `/sessions` to resume, `--resume` from CLI
- [x] **`/tokens`** — show token usage for the current session
- [x] **Token counter** — shown automatically after each response
- [x] **JSON config** — `pix3lcode_config.json` for URL, model, timeouts, context thresholds and prompt
- [x] **Auto retry** — exponential backoff (2s, 4s, 8s…) for N configurable attempts
- [x] **Configurable timeout** — `api_timeout` and `api_retries` in config file
- [x] **Context truncation warning** — warns when context exceeds configured threshold (default 70%)
- [x] **Profiles** — `./pix3lcode.sh --profile coding` loads `profiles/coding.json` with dedicated model and prompt
- [x] **Project context** — reads `CONTEXT.md` from current directory and appends to system prompt
- [x] **`/init`** — analyzes the project and generates `CONTEXT.md` automatically
- [x] **Non-interactive mode** — `./pix3lcode.sh "prompt"` responds and exits; supports stdin pipe

## Architecture

- [x] **Split into modules** — split into `config.py`, `tools.py`, `git_tools.py`, `session.py`, `context.py`, `agent.py`, `main.py` as entry point.
- [x] **Eliminate global state** — `cfg`, `MODEL`, `args`, `client` collected into `AppContext` dataclass and passed explicitly.
