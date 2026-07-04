"""Router identifier extraction + token estimation tests."""

from __future__ import annotations

from codesherpa.retrieve.router import extract_identifier_tokens, split_identifier
from codesherpa.retrieve.tokens import estimate_tokens, result_token_cost


class TestExtractIdentifierTokens:
    def test_snake_case_qualifies(self):
        assert extract_identifier_tokens("what does retry_request do") == ["retry_request"]

    def test_camel_case_qualifies(self):
        assert extract_identifier_tokens("callers of fetchWithRetry please") == ["fetchWithRetry"]

    def test_pascal_case_qualifies(self):
        assert "TaskStore" in extract_identifier_tokens("TaskStore")

    def test_plain_english_words_do_not_qualify(self):
        # none of these words carries identifier morphology
        assert extract_identifier_tokens("how do we validate email addresses") == []
        assert extract_identifier_tokens("password hashing implementation") == []

    def test_single_token_query_always_qualifies(self):
        assert extract_identifier_tokens("slugify") == ["slugify"]

    def test_single_token_with_surrounding_whitespace(self):
        assert extract_identifier_tokens("  slugify \n") == ["slugify"]

    def test_stacktrace_yields_frame_symbols(self):
        trace = (
            "Traceback (most recent call last):\n"
            '  File "pyserver/routes/tasks.py", line 32, in complete_task\n'
            "    task_id = payload[\"task_id\"]\n"
            "KeyError: 'task_id'"
        )
        tokens = extract_identifier_tokens(trace)
        assert "complete_task" in tokens
        assert "task_id" in tokens

    def test_dedup_preserves_first_occurrence_order(self):
        q = "retry_request calls retry_request via fetchWithRetry"
        assert extract_identifier_tokens(q) == ["retry_request", "fetchWithRetry"]

    def test_short_tokens_ignored(self):
        assert extract_identifier_tokens("db") == []  # regex requires len >= 3


class TestSplitIdentifier:
    def test_snake(self):
        assert split_identifier("retry_request") == ["retry", "request"]

    def test_camel(self):
        assert split_identifier("fetchWithRetry") == ["fetch", "with", "retry"]

    def test_pascal_with_acronym(self):
        assert split_identifier("HTTPClient") == ["http", "client"]

    def test_digits(self):
        assert split_identifier("base64_decode2") == ["base64", "decode2"]


class TestEstimateTokens:
    def test_monotone_in_length(self):
        assert estimate_tokens("abcd" * 100) > estimate_tokens("abcd" * 10)

    def test_minimum_one(self):
        assert estimate_tokens("") == 1
        assert estimate_tokens("x") == 1

    def test_deterministic(self):
        s = "def foo(x):\n    return x + 1\n"
        assert estimate_tokens(s) == estimate_tokens(s)

    def test_result_cost_includes_breadcrumb(self):
        assert result_token_cost("a.py :: foo", "code") > estimate_tokens("code")
