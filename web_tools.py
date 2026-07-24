import os
import re
import httpx
from bs4 import BeautifulSoup
from config import AppContext

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the internet for up-to-date information: documentation, "
                "Stack Overflow answers, GitHub issues, library examples, API references. "
                "Returns titles, URLs, and content snippets. "
                "Follow up with fetch_url to read the full content of a page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch and read the text content of a web page. "
                "Use this after web_search to read the full content of a result: "
                "documentation pages, Stack Overflow answers, GitHub READMEs, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the page to fetch",
                    },
                },
                "required": ["url"],
            },
        },
    },
]


def _get_tavily_key(ctx: AppContext) -> str | None:
    """Ottieni la chiave API Tavily dalla configurazione o dalle environment variable.

    :param ctx: Contesto dell'applicazione con accesso alla configurazione
    :return: La chiave API Tavily o None se non configurata
    :rtype: Optional[str]
    """
    return ctx.cfg.get("tavily_api_key") or os.environ.get("TAVILY_API_KEY")


def web_search(query: str, max_results: int = 5, ctx: AppContext = None) -> str:
    api_key = _get_tavily_key(ctx)
    if not api_key:
        return (
            "ERROR: Tavily API key not configured. "
            "Add 'tavily_api_key' to pix3lcode_config.json or set the TAVILY_API_KEY environment variable. "
            "Get a free key at https://app.tavily.com"
        )
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=max_results)
        results = response.get("results", [])
        if not results:
            return "No results found."
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("url", "")
            content = r.get("content", "").strip()
            lines.append(f"[{i}] {title}\n    URL: {url}\n    {content}")
        return "\n\n".join(lines)
    except ImportError:
        return "ERROR: 'tavily-python' library not installed. Run: pip install tavily-python"
    except Exception as e:
        return f"ERROR: {e}"


_BOILERPLATE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "form"]


def _strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_BOILERPLATE_TAGS):
        tag.decompose()
    content = soup.find("main") or soup.find("article") or soup
    text = content.get_text(separator="\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_url(url: str, ctx: AppContext = None) -> str:
    limit = int(ctx.cfg.get("read_file_limit", 100_000))
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; pix3lcode/1.0)"}
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            response = client.get(url, headers=headers)
        content_type = response.headers.get("content-type", "")
        if "html" in content_type:
            text = _strip_html(response.text)
        else:
            text = response.text
        if len(text) > limit:
            truncated_kb = limit // 1024
            text = text[:limit] + f"\n\n[…page truncated at {truncated_kb}KB]"
            ctx.console.print(f"  [yellow]⚠ fetch_url: page truncated to {truncated_kb}KB[/yellow]")
        return text
    except Exception as e:
        return f"ERROR: {e}"


def make_dispatch(ctx: AppContext) -> dict:
    return {
        "web_search": lambda a: web_search(a["query"], a.get("max_results", 5), ctx),
        "fetch_url": lambda a: fetch_url(a["url"], ctx),
    }
