import os
import re
import httpx
from bs4 import BeautifulSoup
from .config import AppContext

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


def _get_searxng_url(ctx: AppContext) -> str | None:
    """Ottieni l'URL base dell'istanza SearXNG dalla configurazione o dalle environment variable.

    :param ctx: Contesto dell'applicazione con accesso alla configurazione
    :return: L'URL base di SearXNG (senza trailing slash) o None se non configurato
    :rtype: Optional[str]
    """
    url = ctx.cfg.get("searxng_url") or os.environ.get("SEARXNG_URL")
    return url.rstrip("/") if url else None


def web_search(query: str, max_results: int = 5, ctx: AppContext = None) -> str:
    base_url = _get_searxng_url(ctx)
    if not base_url:
        return (
            "ERROR: SearXNG URL not configured. "
            "Add 'searxng_url' to pix3lcode_config.json (e.g. 'http://192.168.1.103:8888') "
            "or set the SEARXNG_URL environment variable."
        )
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{base_url}/search",
                params={"q": query, "format": "json"},
            )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])[:max_results]
        if not results:
            return "No results found."
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("url", "")
            content = r.get("content", "").strip()
            lines.append(f"[{i}] {title}\n    URL: {url}\n    {content}")
        return "\n\n".join(lines)
    except httpx.HTTPStatusError as e:
        return f"ERROR: SearXNG returned HTTP {e.response.status_code}. Make sure 'json' is enabled in search.formats in your SearXNG settings.yml."
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
