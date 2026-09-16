"""Simple, explainable keyword search over the knowledge base.

No embeddings or vector databases. The question is lower-cased and split into
tokens, common stop words are removed, and a light stemming rule plus prefix
matching catch simple word variants (print/printer/printing, wifi, syncing,
slow/slowly...). Each query term earns points for every field it matches:

    exact match:      title +3, keywords +2, description +1, solution +1
    prefix match:     +1 in the field where it occurs

Articles scoring at least MIN_SCORE are ranked by score (then title, for a
stable order) and the best TOP_K are returned. If nothing scores high enough
the result is empty - the caller then tells the LLM that no knowledge-base
context was found (the "no strong match" fallback).
"""

import re

WORD_RE = re.compile(r"[a-z0-9]+")

DEFAULT_TOP_K = 3
MIN_SCORE = 2

FIELD_WEIGHTS = (("title", 3), ("keywords", 2), ("description", 1), ("solution", 1))

STOPWORDS = frozenset(
    """
    a an the and or but if then than so because as of at by for from in into on to
    with about over under again further once here there all any both each few more
    most other some such only own same too very s t can will just don should now
    i me my myself we us our ours you your yours he him his she her hers it its
    they them their theirs this that these those am is are was were be been being
    do does did doing have has had having what which who whom when where why how
    not no nor cant wont dont doesnt didnt isnt arent wasnt werent hasnt havent
    please help me my get got need want know
    """.split()
)

# Longest-first so that e.g. "ies" is tried before "s".
_SUFFIXES = ("ies", "ing", "ed", "es", "ly", "s", "e")


def _stem(word: str) -> str:
    """Very light stemming: strip a few common suffixes (min stem length 3).

    Examples: printing->print, printers->printer, crashes->crash,
    slowly->slow, syncing->sync, policies->policy.
    """
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix == "ies":
                return word[:-3] + "y"
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    """Lower-case and split into alphanumeric tokens (length >= 2).

    Hyphenated words are indexed twice - as parts and joined - so that
    "wi-fi" matches both "wi fi" and "wifi".
    """
    tokens: list[str] = []
    for word in text.lower().split():
        parts = [part for part in WORD_RE.findall(word) if len(part) >= 2]
        if not parts:
            continue
        tokens.extend(parts)
        if len(parts) > 1:
            joined = "".join(parts)
            if joined not in tokens:
                tokens.append(joined)
    return tokens


def extract_terms(text: str) -> set[str]:
    """Stemmed set of significant (non stop-word) terms in `text`."""
    stems = {_stem(token) for token in tokenize(text) if token not in STOPWORDS}
    return {stem for stem in stems if stem and stem not in STOPWORDS}


def _prefix_match(term: str, stems: set[str]) -> bool:
    """True when `term` shares a >= 4 character prefix with a field stem."""
    if len(term) < 4:
        return False
    return any(
        len(stem) >= 4 and (stem.startswith(term) or term.startswith(stem))
        for stem in stems
    )


def score_article(terms: set[str], article) -> int:
    """Relevance score of one article for the given query terms."""
    stems_by_field = {
        field: extract_terms(getattr(article, field, "") or "")
        for field, _weight in FIELD_WEIGHTS
    }
    score = 0
    for term in terms:
        for field, weight in FIELD_WEIGHTS:
            stems = stems_by_field[field]
            if term in stems:
                score += weight
            elif _prefix_match(term, stems):
                score += 1
    return score


def search_articles(query: str, articles, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """Return the most relevant knowledge-base articles for `query`.

    Each result is a dict with id/title/description/solution/score, best
    first. Returns an empty list when nothing matches well enough.
    """
    if not query or not articles:
        return []
    terms = extract_terms(query)
    if not terms:
        return []

    scored = []
    for article in articles:
        score = score_article(terms, article)
        if score >= MIN_SCORE:
            scored.append(
                {
                    "id": article.id,
                    "title": article.title,
                    "description": article.description,
                    "solution": article.solution,
                    "score": score,
                }
            )
    scored.sort(key=lambda item: (-item["score"], item["title"].lower()))
    return scored[:top_k]
