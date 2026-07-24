# Pix3lCode

A terminal chat application powered by [LM Studio](https://lmstudio.ai/), with tool calling support for reading/writing files, executing shell commands, and searching code — similar to Claude Code but running entirely on local models.

## Features

- **Interactive chat** in the terminal with history (arrow keys)
- **Response streaming** — text appears word by word as the model generates it
- **Tool calling** — the model can autonomously use tools to complete tasks
- **Vision support** — image paths in your message are attached automatically (JPEG, PNG, WebP, …); no special command needed
- **Session management** — auto-save and resume previous conversations
- **Token counter** — tracks context usage and warns before the limit is reached
- **Retry logic** — automatic exponential backoff on API failures
- **JSON configuration** — all parameters configurable without touching the code
- **Profiles** — named configurations for different contexts (coding, linux, writing…)
- **Project context** — automatically loads `CONTEXT.md` from the current directory into the system prompt
- **Non-interactive mode** — pass a prompt as argument or pipe from stdin for use in scripts
- **Interactive setup** — guided wizard that reads available models directly from LM Studio

### Available tools

| Tool | Description |
|---|---|
| `read_file` | Read any file from the filesystem, including PDF text extraction (truncates at configurable limit) |
| `write_file` | Write or create a file (asks confirmation) |
| `patch_file` | Replace a specific portion of a file (old → new, asks confirmation) |
| `list_directory` | List files and folders in a directory |
| `execute_shell` | Run a Linux shell command (asks confirmation for dangerous ones) |
| `search_files` | Search text in files with regex, like grep |
| `web_search` | Search the internet via Tavily (documentation, Stack Overflow, GitHub issues…) |
| `fetch_url` | Fetch and read the text content of a web page |
| `git_status` | Show git repository status |
| `git_diff` | Show diff (staged or unstaged) |
| `git_log` | Show commit history |
| `git_commit` | Run git add + commit (asks confirmation) |

## Requirements

- Python 3.11+ and [pipx](https://pipx.pypa.io/)
- [LM Studio](https://lmstudio.ai/) running with a model that supports tool calling (e.g. Qwen3, Devstral)
- For vision: a multimodal model loaded in LM Studio (e.g. Qwen2-VL, LLaVA)
- For PDF reading: `pypdf` (installed automatically as a dependency)
- For web search: a [Tavily](https://app.tavily.com) API key (free tier: 2000 queries/month)

## Installation

Requires [pipx](https://pipx.pypa.io/) (installs Python CLI tools into isolated venvs and puts them on your `PATH`):

```bash
# Debian/Ubuntu
sudo apt install pipx
pipx ensurepath

# or via pip
python3 -m pip install --user pipx
pipx ensurepath
```

Then install pix3lcode:

```bash
# Clone the repository
git clone <repo-url>
cd pix3lcode

# Editable install (recommended if you plan to modify the code — changes
# take effect immediately, no reinstall needed)
pipx install -e .

# Or a regular install from a built wheel
python3 -m pip install --user build
python3 -m build --wheel
pipx install dist/pix3lcode-*.whl
```

`pix3lcode` and `pix3lcode-setup` are now available from any directory. Upgrade with `pipx upgrade pix3lcode`, remove with `pipx uninstall pix3lcode`.

## Setup

Run the interactive setup wizard to generate your configuration file. It connects to LM Studio, fetches the list of loaded models, and guides you through all parameters:

```bash
pix3lcode-setup
```

The wizard will ask:
- LM Studio API URL
- Which model to use (fetched automatically from LM Studio)
- Context window size (token limit for the chosen model)
- Warning threshold (e.g. `60` to be warned at 60% context usage)
- API timeout, shell timeout, retry attempts
- Sessions directory
- System prompt (optional)

Configuration is saved to `pix3lcode_config.json` in the current directory (project-specific) or to `~/.pix3lcode_config.json` (global). Re-run `pix3lcode-setup` any time you switch models.

## Usage

```bash
# Start a new session
pix3lcode

# Use a specific model
pix3lcode --model mistralai/devstral-small-2-2512
pix3lcode -m qwen/qwen3-5b

# Resume the last session (shows a list to choose from)
pix3lcode --resume
pix3lcode -r

# Resume a specific session by ID
pix3lcode --resume 20240418_143022

# Use an alternative config file
pix3lcode --config ~/configs/coding.json

# Use a named profile (from profiles/ directory)
pix3lcode --profile coding
pix3lcode -p linux

# Non-interactive mode: single prompt, print response and exit
pix3lcode "scrivi un hello world in rust"
pix3lcode -p coding "trova bug in questo codice" < main.py

# Pipe from stdin
cat error.log | pix3lcode "cosa significa questo errore?"
git diff | pix3lcode "scrivi un messaggio di commit"

# Auto-confirm dangerous shell commands (for use in scripts)
pix3lcode --yes "pulisci la directory build"

# Pure chat mode without tools (saves tokens in system prompt)
pix3lcode --no-tools

# Print the installed version
pix3lcode --version
```

## Commands

| Command | Description |
|---|---|
| `/help` | Show all available commands and tools |
| `/model` | Show the active model and LM Studio URL |
| `/tokens` | Show token usage for the current session |
| `/sessions` | List saved sessions and switch to one (d\<n\> to delete) |
| `/undo` | Remove the last user+assistant exchange from history |
| `/export` | Export the session to a markdown file in the current directory |
| `/rename <name>` | Rename the current session |
| `/cd <path>` | Change working directory (affects file and shell tools) |
| `/compact` | Summarize the conversation to free up context |
| `/init` | Analyze the project and generate `CONTEXT.md` |
| `/doxygen [path]` | Add Doxygen comments to a file or directory (asks if no path given) |
| `/clear` | Clear history and start a new session |
| `/exit` | Save and exit |
| `Ctrl+C` | Save and exit |

## Configuration

Copy `pix3lcode_config.json` to your project directory or to `~/.pix3lcode_config.json` for global settings.

**Priority order:** project directory > home directory > built-in defaults

> **Note:** `pix3lcode_config.json` may contain API keys — add it to `.gitignore` to avoid committing secrets.

```json
{
  "base_url": "http://10.5.0.2:1234/v1",
  "model": "qwen/qwen3-5b",
  "sessions_dir": "~/.pix3lcode_sessions",
  "shell_timeout": 60,
  "api_timeout": 120,
  "api_retries": 3,
  "context_limit": 80000,
  "context_warn_threshold": 0.70,
  "system_prompt": "You are a helpful AI assistant..."
}
```

| Key | Default | Description |
|---|---|---|
| `base_url` | `http://10.5.0.2:1234/v1` | LM Studio API URL |
| `model` | `qwen/qwen3-5b` | Default model name |
| `sessions_dir` | `~/.pix3lcode_sessions` | Directory for saved sessions |
| `shell_timeout` | `60` | Shell command timeout (seconds) |
| `api_timeout` | `120` | API call timeout (seconds) |
| `api_retries` | `3` | Max retry attempts on API failure |
| `context_limit` | `80000` | Model context window size (tokens) |
| `context_warn_threshold` | `0.70` | Warn when context exceeds this fraction |
| `max_tool_iterations` | `20` | Max tool calls per response before stopping |
| `read_file_limit` | `100000` | Max bytes read from a file (truncates with warning) |
| `system_prompt` | *(built-in)* | System prompt for the model |
| `tavily_api_key` | *(none)* | Tavily API key for `web_search` (or set `TAVILY_API_KEY` env var) |

## Project context

If a `CONTEXT.md` file exists in the current directory, it is automatically appended to the system prompt at startup. Use it to give the model persistent knowledge about your project.

Run `/init` to generate it automatically — the model explores the project structure and key files, then writes `CONTEXT.md` for you. Best used with a large-context model (9B, 80k tokens):

```bash
pix3lcode          # start with large-context model
/init             # generates CONTEXT.md by reading the project
/exit             # save and exit

pix3lcode -p coding  # next sessions start with CONTEXT.md already loaded
```

If `CONTEXT.md` already exists, `/init` asks before overwriting.

You can also write it manually:

```markdown
# MyProject

Python web API built with FastAPI. Main entry point is `src/main.py`.
Database: PostgreSQL via SQLAlchemy. Tests in `tests/` with pytest.
Conventions: snake_case, type hints required, no print() in production code.
```

The startup panel shows `Project context: CONTEXT.md loaded` when the file is found.

## Vision support

If your model supports images (e.g. Qwen2-VL, LLaVA), just include an image path anywhere in your message — the app attaches it automatically:

```
You: what's wrong with this UI? /home/paolo/screenshots/error.png
You: compare these two diagrams ./arch_v1.png ./arch_v2.png
```

Supported formats: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.bmp`

The app prints `Image attached: filename.png` as confirmation and encodes the image as a base64 data URL in the API request.

## Non-interactive mode

Pass a prompt directly as argument — the tool responds once and exits. Useful in scripts and pipelines:

```bash
# Single prompt
pix3lcode "scrivi un hello world in rust"

# Pipe file content
cat src/main.py | pix3lcode "trova potenziali bug"

# Git integration
git diff | pix3lcode "scrivi un messaggio di commit"

# With profile
pix3lcode -p coding "refactora questa funzione" < utils.py

# Skip confirmation for dangerous commands (use with care)
pix3lcode --yes "rimuovi i file temporanei in build/"
```

## Profiles

Profiles are named JSON files that override only the parameters they define — the rest fall back to `pix3lcode_config.json` or built-in defaults. Built-in profiles ship with the package; your own custom profiles go in `~/.pix3lcode_profiles/` (checked first, so a user profile can also override a built-in one of the same name).

```bash
pix3lcode --profile coding    # loads ~/.pix3lcode_profiles/coding.json if present, else the built-in one
pix3lcode -p linux
```

A few example profiles are included:

| Profile | Model | Context | Use case |
|---|---|---|---|
| `coding` | large model | 18k | complex code tasks requiring better reasoning |
| `linux` | fast model | 80k | shell, sysadmin, long sessions |
| `qt` | large model | — | Qt/C++ development |

Create your own:

```bash
mkdir -p ~/.pix3lcode_profiles
cat > ~/.pix3lcode_profiles/myprofile.json << 'EOF'
{
  "model": "my-model-name",
  "context_limit": 32000,
  "system_prompt": "You are a..."
}
EOF
pix3lcode -p myprofile
```

The active profile name is shown in the startup panel.

## Context management

The tool tracks token usage and warns you when approaching the context limit:

- **Yellow warning** at 70% — consider using `/compact`
- **Red warning** at 100% — use `/compact` or `/clear` immediately

`/compact` asks the model to summarize the entire conversation into a few paragraphs, then restarts from that summary — freeing up most of the context window.

## Session management

Sessions are saved automatically to `~/.pix3lcode_sessions/` after every exchange and on exit. Each session is a JSON file named by timestamp (e.g. `20240418_143022.json`).

```bash
# Resume interactively
pix3lcode --resume

# Resume a specific session
pix3lcode --resume 20240418_143022
```

You can also switch sessions mid-conversation with `/sessions`.

## Web search

The `web_search` tool lets the model search the internet for up-to-date information during a task — documentation, Stack Overflow answers, GitHub issues, library changelogs, and more. After finding relevant links, it can use `fetch_url` to read the full content of any page.

To enable it, add your Tavily API key to `pix3lcode_config.json`:

```json
{
  "tavily_api_key": "tvly-..."
}
```

Or set the environment variable `TAVILY_API_KEY`. Get a free key at [app.tavily.com](https://app.tavily.com) (2000 queries/month on the free tier).

## Security

Commands containing potentially dangerous patterns (`rm`, `sudo`, `kill`, `dd`, `chmod`, `pip install`, `apt`, `curl | bash`, etc.) require explicit confirmation before execution:

```
⚠ Potentially dangerous command:
  rm -rf build/
  Execute? [y/N]:
```

`write_file` and `patch_file` also ask for confirmation before modifying files.

## License

MIT
