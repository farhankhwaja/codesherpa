"""Query-focused CE passage selection tests (retrieve/passages.py)."""

from __future__ import annotations

from repograph.retrieve.passages import focus_passage, query_terms


class TestQueryTerms:
    def test_plain_words(self):
        assert query_terms("where is the retry logic") >= {"retry", "logic", "where"}

    def test_identifier_split(self):
        terms = query_terms("callers of fetchWithRetry")
        assert {"fetchwithretry", "fetch", "with", "retry"} <= terms

    def test_short_tokens_dropped(self):
        assert "is" not in query_terms("where is it")


class TestFocusPassage:
    def test_small_chunk_returned_whole(self):
        out = focus_passage({"retry"}, "crumb", "tiny code", 200)
        assert out == "crumb\ntiny code"

    def test_breadcrumb_always_present(self):
        code = "x = 1\n" * 200
        out = focus_passage({"retry"}, "a.py :: module", code, 300)
        assert out.startswith("a.py :: module\n")
        assert len(out) <= 300

    def test_window_covers_matching_lines_deep_in_chunk(self):
        filler = "\n".join(f"const pad{i} = {i};" for i in range(60))
        target = (
            "export function getToken() {\n"
            "  return localStorage.getItem('auth');\n"
            "}\n"
        )
        code = filler + "\n" + target + filler
        out = focus_passage(
            query_terms("why does the app forget I'm logged in — token storage"),
            "webclient/src/auth.ts :: auth",
            code,
            400,
        )
        assert "getToken" in out, "window must land on the matching region"

    def test_no_matches_prefers_head(self):
        code = "\n".join(f"line {i}" for i in range(100))
        out = focus_passage({"zzz"}, "crumb", code, 120)
        assert "line 0" in out

    def test_never_exceeds_max_chars(self):
        code = ("someToken " * 50 + "\n") * 50
        out = focus_passage({"sometoken"}, "b" * 100, code, 500)
        assert len(out) <= 500

    def test_single_overlong_line(self):
        code = "x" * 5000
        out = focus_passage({"x"}, "crumb", code, 200)
        assert len(out) <= 200

    def test_deterministic(self):
        code = "\n".join(f"def fn_{i}(): pass" for i in range(200))
        a = focus_passage({"fn_77"}, "crumb", code, 300)
        b = focus_passage({"fn_77"}, "crumb", code, 300)
        assert a == b
