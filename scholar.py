"""Semantic Scholar: matching a paper to its record by title, and suggesting
papers like a set of them. The only part of the app that goes online. A free
key in S2_API_KEY lifts the shared rate limit; it works without one."""

import json
import os
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import streamlit as st

API = "https://api.semanticscholar.org"


def _call(path: str, body: dict | None = None):
    """GET `path`, or POST `body` to it, as JSON. None when there is no such
    record; a busy server (429) is retried, waiting longer each time."""
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = key
    request = Request(API + path, headers=headers,
                      data=None if body is None else json.dumps(body).encode())
    for wait in (1, 2, 4, None):
        try:
            with urlopen(request, timeout=10) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code != 429 or wait is None:
                raise
            time.sleep(wait)


def match(title: str) -> str:
    """The Semantic Scholar id of the paper closest to `title`, or "" when
    nothing is close, so a paper is looked up only once."""
    found = _call("/graph/v1/paper/search/match?fields=paperId&query="
                  + quote(title))
    return found["data"][0]["paperId"] if found and found.get("data") else ""


@st.cache_data(ttl="1h", show_spinner="Asking Semantic Scholar…")
def suggest(liked: tuple[str, ...], disliked: tuple[str, ...]) -> list[dict]:
    """Papers like those in `liked` and unlike those in `disliked`, best first.
    Cached for an hour per pair, as these change slowly."""
    found = _call("/recommendations/v1/papers/?limit=100"
                  "&fields=title,year,venue,url,externalIds",
                  {"positivePaperIds": list(liked),
                   "negativePaperIds": list(disliked)})
    return found["recommendedPapers"] if found else []


def link(paper: dict) -> str:
    """Where to read a suggested paper: its DOI where it has one, else its
    Semantic Scholar page."""
    doi = (paper.get("externalIds") or {}).get("DOI")
    return f"https://doi.org/{doi}" if doi else paper["url"]
