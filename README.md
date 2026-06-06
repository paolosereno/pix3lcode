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

- Python 3.11+
- [LM Studio](https://lmstudio.ai/) running with a model that supports tool calling (e.g. Qwen3, Devstral)
- For vision: a multimodal model loaded in LM Studio (e.g. Qwen2-VL, LLaVA)
- For PDF reading: `pypdf` (installed automatically via `requirements.txt`)
- For web search: a [Tavily](https://app.tavily.com) API key (free tier: 2000 queries/month)

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd pix3lcode

# Create virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Setup

Run the interactive setup wizard to generate your configuration file. It connects to LM Studio, fetches the list of loaded models, and guides you through all parameters:

```bash
./setup.sh
```

The wizard will ask:
- LM Studio API URL
- Which model to use (fetched automatically from LM Studio)
- Context window size (token limit for the chosen model)
- Warning threshold (e.g. `60` to be warned at 60% context usage)
- API timeout, shell timeout, retry attempts
- Sessions directory
- System prompt (optional)

Configuration is saved to `pix3lcode_config.json` in the current directory (project-specific) or to `~/.pix3lcode_config.json` (global). Re-run `./setup.sh` any time you switch models.

## Usage

```bash
# Start a new session
./pix3lcode.sh

# Use a specific model
./pix3lcode.sh --model mistralai/devstral-small-2-2512
./pix3lcode.sh -m qwen/qwen3-5b

# Resume the last session (shows a list to choose from)
./pix3lcode.sh --resume
./pix3lcode.sh -r

# Resume a specific session by ID
./pix3lcode.sh --resume 20240418_143022

# Use an alternative config file
./pix3lcode.sh --config ~/configs/coding.json

# Use a named profile (from profiles/ directory)
./pix3lcode.sh --profile coding
./pix3lcode.sh -p linux

# Non-interactive mode: single prompt, print response and exit
./pix3lcode.sh "scrivi un hello world in rust"
./pix3lcode.sh -p coding "trova bug in questo codice" < main.py

# Pipe from stdin
cat error.log | ./pix3lcode.sh "cosa significa questo errore?"
git diff | ./pix3lcode.sh "scrivi un messaggio di commit"

# Auto-confirm dangerous shell commands (for use in scripts)
./pix3lcode.sh --yes "pulisci la directory build"

# Pure chat mode without tools (saves tokens in system prompt)
./pix3lcode.sh --no-tools
```

### Optional: global alias

```bash
echo "alias pix3lcode='/path/to/pix3lcode/pix3lcode.sh'" >> ~/.bashrc
source ~/.bashrc
# Then just type:
pix3lcode
pix3lcode --resume
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
./pix3lcode.sh          # start with large-context model
/init             # generates CONTEXT.md by reading the project
/exit             # save and exit

./pix3lcode.sh -p coding  # next sessions start with CONTEXT.md already loaded
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
./pix3lcode.sh "scrivi un hello world in rust"

# Pipe file content
cat src/main.py | ./pix3lcode.sh "trova potenziali bug"

# Git integration
git diff | ./pix3lcode.sh "scrivi un messaggio di commit"

# With profile
./pix3lcode.sh -p coding "refactora questa funzione" < utils.py

# Skip confirmation for dangerous commands (use with care)
./pix3lcode.sh --yes "rimuovi i file temporanei in build/"
```

## Profiles

Profiles are JSON files stored in the `profiles/` directory. Each profile overrides only the parameters it defines — the rest fall back to `pix3lcode_config.json` or built-in defaults.

```bash
./pix3lcode.sh --profile coding    # loads profiles/coding.json
./pix3lcode.sh -p linux            # loads profiles/linux.json
```

Two example profiles are included:

| Profile | Model | Context | Use case |
|---|---|---|---|
| `coding` | large model | 18k | complex code tasks requiring better reasoning |
| `linux` | fast model | 80k | shell, sysadmin, long sessions |

Create your own by adding a JSON file to `profiles/`:

```json
// profiles/myprofile.json
{
  "model": "my-model-name",
  "context_limit": 32000,
  "system_prompt": "You are a..."
}
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
./pix3lcode.sh --resume

# Resume a specific session
./pix3lcode.sh --resume 20240418_143022
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
