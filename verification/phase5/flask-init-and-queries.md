# Phase 5 external-repo validation — pallets/flask

Date: 2026-07-04 · branch phase-5 (post-D30 wiring) · Apple M-series, CPU-only.
Clone: github.com/pallets/flask @ HEAD of default branch on this date.

## repograph init (end-to-end, cold)

Repo: 236 tracked files, 38,330 LOC, .git 13 MB.

```
$ repograph init .
repograph: initialized <clone>/.repograph/index.db
repograph: hooks installed: post-merge, post-checkout, post-rewrite, post-commit
repograph: .gitignore updated
repograph: first index: 224 blobs, 616 chunks, 230 files (0.32s)
repograph: embedding 616 chunks (CPU; incremental — only new chunks are ever re-embedded)
repograph: embedding chunks 0/616 (0%)
repograph: embedding chunks 64/616 (10%)
  … 10% steps …
repograph: embedding chunks 616/616 (100%)
real 231.54   (total wall: 0.32 s parse+store+graph, ~228 s nomic embedding)
```

Index size: 12.98 MB (vs 13 MB .git, 38.3k LOC). No crashes; progress
printed throughout (amendment 3f verified in the wild).

## 5 sample queries (`repograph search`, shipping defaults)

1. `how does the application register a blueprint`
   → **src/flask/sansio/blueprints.py :: Blueprint.register** (rank 1),
   BlueprintSetupState (2), iter_blueprints (5), _merge_blueprint_funcs via
   1-hop expansion ("called by register"). Sensible ✓

2. `where is a view function's return value converted into a response object`
   → **src/flask/helpers.py :: make_response** (rank 1),
   **src/flask/app.py :: Flask.make_response** body chunk (4),
   Flask.process_response (6). Sensible ✓

3. `load configuration from environment variables with a prefix`
   → **src/flask/config.py :: Config.from_prefixed_env** (rank 1),
   from_envvar (2), from_object/from_pyfile below; expansion attached the
   celery example that calls from_prefixed_env. Sensible ✓

4. `full_dispatch_request` (router fast path)
   → exact definition **src/flask/app.py :: Flask.full_dispatch_request**
   plus ranked 1-hop neighbors (wsgi_app calls it; preprocess_request /
   handle_user_exception called by it). **real 0.07 s** — no model load. ✓

5. `TypeError: The view function did not return a valid response` (stack-trace style)
   → **src/flask/app.py :: Flask.make_response** interior chunk (rank 1) —
   exactly where that TypeError is raised. Sensible ✓

Full raw output retained in the session log; nothing edited beyond
truncation of trailing low-score rows.
