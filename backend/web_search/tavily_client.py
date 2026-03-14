"""Tavily web search client — isolated module, no cross-dependencies."""

import os

import requests
import urllib3
from tavily import TavilyClient

# Suppress the InsecureRequestWarning that fires when verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _make_session() -> requests.Session:
    """Return a requests.Session with SSL verification disabled (corporate proxy safe)."""
    session = requests.Session()
    session.verify = False  # noqa: S501 — required for corporate SSL inspection proxies
    return session


def search(query: str, max_results: int = 5) -> list[dict]:
    """Run a Tavily web search and return up to *max_results* clean result dicts."""
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        raise ValueError("TAVILY_API_KEY environment variable is not set.")

    client = TavilyClient(api_key=api_key, session=_make_session())
    response = client.search(
        query=query,
        search_depth="basic",
        max_results=max_results,
        include_answer=False,
    )

    results: list[dict] = []
    for r in response.get("results", [])[:max_results]:
        results.append(
            {
                "title": r.get("title") or "",
                "url": r.get("url") or "",
                "content": r.get("content") or "",
                "score": float(r.get("score") or 0.0),
            }
        )
    return results
