"""Unit tests for the knowledge-base keyword search."""

from types import SimpleNamespace

from backend.knowledge_base import SEED_ARTICLES
from backend.search import (
    extract_terms,
    search_articles,
    tokenize,
)

ARTICLES = [
    SimpleNamespace(id=i + 1, **article)
    for i, article in enumerate(SEED_ARTICLES)
]


def titles(results):
    return [item["title"] for item in results]


def test_tokenize_normalizes_case_and_splits():
    assert tokenize("Wi-Fi NOT connecting!") == ["wi", "fi", "wifi", "not", "connecting"]


def test_extract_terms_removes_stopwords_and_stems():
    terms = extract_terms("The printers are not printing slowly")
    assert "print" in terms          # printing -> print
    assert "printer" in terms        # printers -> printer
    assert "slow" in terms           # slowly -> slow
    assert "the" not in terms and "not" not in terms and "are" not in terms


def test_wifi_question_finds_wifi_article_first():
    results = search_articles("My Wi-Fi keeps disconnecting at the office", ARTICLES)
    assert results, "expected at least one match"
    assert results[0]["title"] == "Wi-Fi not connecting"


def test_printer_question_finds_printer_article_first():
    results = search_articles("printer shows offline and nothing prints", ARTICLES)
    assert results[0]["title"] == "Printer not printing"


def test_dns_question_finds_dns_article_first():
    results = search_articles("cannot open any websites, DNS probe error", ARTICLES)
    assert results[0]["title"] == "DNS problem - websites not resolving"


def test_slow_computer_question():
    results = search_articles("everything on my PC is very slow and booting takes ages", ARTICLES)
    assert "Computer running slowly" in titles(results)


def test_results_are_limited_and_sorted():
    results = search_articles("wifi internet slow network", ARTICLES)
    assert len(results) <= 3
    scores = [item["score"] for item in results]
    assert scores == sorted(scores, reverse=True)


def test_unrelated_question_returns_no_matches():
    results = search_articles("What is the best pizza restaurant in Rome?", ARTICLES)
    assert results == []


def test_empty_or_stopword_only_query_returns_no_matches():
    assert search_articles("", ARTICLES) == []
    assert search_articles("   ", ARTICLES) == []
    assert search_articles("the and or not", ARTICLES) == []
