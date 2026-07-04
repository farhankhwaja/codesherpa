# Phase 5 external-repo validation — sizly (local repo)

Date: 2026-07-04 · branch phase-5 · Apple M-series, CPU-only.
Repo: local clone of /Users/farhankhwaja/Desktop/personal/sizly (Node/Express
backend + React/Vite PWA frontend; .js/.jsx via the javascript grammar).

**Redaction note:** per the Phase 5 instructions no sizly file *content* is
committed here — transcripts reference file paths, byte ranges, scores, and
sources only.

## repograph init (end-to-end, cold)

Repo: 104 tracked files, 29,193 LOC, .git 4.5 MB.

```
$ repograph init .
repograph: first index: 95 blobs, 216 chunks, 95 files (0.18s)
repograph: embedding 216 chunks (CPU; incremental — …)
repograph: embedding chunks 0/216 (0%) … 216/216 (100%)
real 73.73   (0.18 s parse+store+graph, ~71 s nomic embedding)
```

Index size: 5.9 MB. Hooks installed, .gitignore updated, no crashes.

## 5 sample queries (paths/scores only)

1. `figure out the brand name from a pasted product link`
   → frontend/src/utils/brandExtractor.js (rank 1, symbol) and
   backend/utils/brandExtractor.js (ranks 2 & 4) — both duplicated copies
   surfaced. ✓

2. `retry when the connection to the AI provider drops midway`
   → backend/ai/fitRecommend.js[14195:14795] (rank 1, bm25) — the
   connection-retry region. ✓

3. `requireUser` (router fast path) — **0 ms**
   → exact definition backend/middleware/auth.js[1301:2156] + 1-hop
   expansion backend/index.js (imports it). ✓

4. `stop a single caller from hammering an expensive endpoint`
   → backend/middleware/rateLimit.js at rank 4; push-notification modules
   rank above it (they mention send limits). Partial — right file present
   in top-5, not rank 1.

5. `decide whether a returning member skips the first-time setup flow`
   → frontend/src/hooks/useProfile.js[1719:2841] rank 2 (the
   onboarding-derivation region); backend fitCheckScheduler rank 1 (decoy).
   Right file in top-2. ✓

Overall: 5/5 queries put the correct file in the top-5; 3/5 at rank 1.
