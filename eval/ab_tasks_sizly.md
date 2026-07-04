# Code-Retrieval Benchmark — Sizly

Repository: `/Users/farhankhwaja/Desktop/personal/sizly`

A code-retrieval / code-navigation evaluation for this repository. Each task is
stated purely in terms of observable behavior or intent — no file paths, symbol
names, or identifiers appear in the task text. The tool under test must locate
the relevant code from the description alone.

Repo shape (for graders, not for the tool): a `backend/` (Node + Express, ESM —
product detection via Gemini grounding with a GPT-4o slug fallback, and a GPT-4o
size-recommendation engine) and a `frontend/` (React + Vite + Tailwind PWA).
Ground truth for each task is recorded in an HTML comment and cites files,
symbols, and the commit the answer was derived from. All cited paths/symbols
were verified to exist in the working tree at authoring time.

Scoring suggestion: award full credit only when the tool names the primary
file(s) AND the specific function/symbol; partial credit for the correct file
without the symbol; zero for the wrong module.

---

## Debugging tasks (5)

Each describes a real defect that was previously fixed, re-framed as if it just
resurfaced and the developer doesn't yet know where it lives.

### D1
Symptom: During first-time setup, a person enters the size they own for one
clothing category, and the input immediately jumps them into a *different*
category on its own — they never asked to move on, and it feels like the form
is racing ahead of them. It should save what they entered, settle, and only
advance to another category when they explicitly choose to add one.
Task: locate the responsible code and explain the fix.

<!--
GROUND TRUTH (commit 26a34bc "fix(onboarding): no auto-advance between size categories")
- frontend/src/components/onboarding/ManualSizeSelect.jsx
  - BrandSizeEntryEditor(): the `adding` state (initialised from whether entries exist),
    commit() now saves + clears + closes the form instead of leaving an empty picker open,
    resetForm(), and the explicit "+ Add another category" button.
Scoring: primary file ManualSizeSelect.jsx + the entry-editor/commit logic.
-->

### D2
Symptom: Pasting a product link usually auto-fills the brand, but for certain
retailers whose web address includes an extra label in front of the main site
name (for example a regional or mobile variant of the host), the brand comes
back empty even though the plain address works fine. And when the brand truly
can't be determined, the app should fall back to asking the shopper to type it
rather than silently leaving it blank.
Task: locate the responsible code and explain the fix.

<!--
GROUND TRUTH (commits 3152b59 "fix(home): recognize subdomains (www2.hm.com) + manual brand for unknown links"
and 24a74bc "refactor(brand): derive domain positionally instead of stripping a TLD list")
- frontend/src/utils/brandExtractor.js AND backend/utils/brandExtractor.js (duplicated logic):
  extractBrandFromUrl() — the SECOND_LEVEL set + positional second-to-last-label derivation
  that ignores subdomains and two-part TLDs; domainMap lookup.
- frontend/src/pages/Home.jsx — surfacing the manual-brand entry path when unknown.
Scoring: extractBrandFromUrl in brandExtractor.js (either/both layers).
-->

### D3
Symptom: In production the size-recommendation step fails on nearly every
request — the connection to the AI provider drops partway through the response
— while the exact same request succeeds on a developer's laptop. The service is
otherwise healthy: the health check is green and product detection still works;
only the size call breaks.
Task: locate the responsible code and explain the fix.

<!--
GROUND TRUTH (commit bda9921 "fix(recommend): switch OpenAI transport to native fetch + deep failure logging";
related a72d386, 25a4d32, dd6702e)
- backend/ai/fitRecommend.js — the OpenAI client construction now passes
  `fetch: (...args) => globalThis.fetch(...args)` (native undici) instead of the SDK's
  default node-fetch transport; getRecommendation() + isConnectionError() retry;
- backend/routes/recommend.js — errorAnatomy() deep failure logging.
- backend/package.json — engines.node pin ("20.x") so builds stop drifting.
(Adjacent root cause also addressed by dns.setDefaultResultOrder('ipv4first') in backend/index.js.)
Scoring: fitRecommend.js OpenAI client transport is the primary answer.
-->

### D4
Symptom: A returning shopper who already finished setup and has a saved profile
is sometimes dropped back into the first-time setup flow after signing in
(notably on a fresh device or a cold start), instead of landing straight on the
main screen. The app is trusting the wrong signal to decide whether setup is
already done.
Task: locate the responsible code and explain the fix.

<!--
GROUND TRUTH (commit 49b3485 "fix(auth): returning users skip onboarding (check profile, not just local flag)")
- frontend/src/hooks/useProfile.js — `onboarded` derived from profile presence (a loaded
  profile ⇒ onboarded), not solely the local flag; `profileLoading` gate on the initial
  Firestore load; persists the flag once a profile is seen.
- frontend/src/App.jsx — the onboarded-vs-home routing decision + waiting on profileLoading
  (Splash) so a returning user isn't flashed into onboarding.
Scoring: useProfile.js onboarding-derivation logic + App.jsx gating.
-->

### D5
Symptom: Google sign-in fails only inside the installed app (it works in a
normal browser tab). The sign-in handshake bounces the user through provider
handoff pages, but instead of those handoff URLs completing, the installed app
serves its own shell over them, so authentication never finishes.
Task: locate the responsible code and explain the fix.

<!--
GROUND TRUTH (commit a6dd37e "fix(auth): stop SW from hijacking /__/auth/* (Google sign-in in PWA)";
related 9819387)
- frontend/vite.config.js — the vite-plugin-pwa workbox config: navigateFallbackDenylist
  excluding the auth-handler paths (/^\/__\//) [and /^\/api\//] so the generated service
  worker stops serving index.html over the Firebase auth handoff routes.
Scoring: vite.config.js workbox navigateFallbackDenylist.
-->

---

## Feature-location tasks (6 — 5 verified, 1 prospective)

"Where would I change things to add / adjust X?" Realistic change requests
spanning backend and frontend; several require cross-file/cross-layer
understanding. F1–F5 mirror real change patterns with verified ground truth;
F6 is a *prospective* feature not yet built — its ground truth lists the
expected integration points in the current code, and graders should score it as
"did the tool find where this would plug in," not against any committed answer.

### F1
Request: We want to offer shoppers one more choice of garment cut/fit intent
(alongside the existing set of fit styles they can tap). It needs to show up as
a selectable option in the UI, be assignable by the automatic detection from a
product link, and flow through to the size recommendation. Where does this
change need to touch?

<!--
GROUND TRUTH (pattern: commit 3bb37c3 "add Slim fit intent end-to-end" and the later Relaxed addition)
CROSS-LAYER. Files:
- frontend/src/utils/constants.js — STYLE_INTENTS array (the selectable list).
- frontend/src/components/recommendation/StyleFilters.jsx — renders the chips from STYLE_INTENTS.
- frontend/src/utils/api.js — composeCategory() (maps the intent into the size-key string).
- backend/ai/groundedInfer.js — mapFitStyle() (Gemini-detected cut → the chip value).
- backend/ai/inferProduct.js — SYSTEM_PROMPT enum + rules (GPT-4o slug detector's allowed styleIntent).
Scoring: full credit requires both the frontend list/UI AND both backend detectors.
-->

### F2
Request: We think we're sending the AI too much (or too little) of the
shopper's past purchases and fit history when it computes a size, and we want
to change what gets included. Where is the data assembled on the way out, and
where is it consumed to build the model's prompt?

<!--
GROUND TRUTH (pattern: commit 72bcb70 "trim the userProfile payload to what the prompt actually reads")
CROSS-LAYER. Files:
- frontend/src/utils/api.js — profileToPayload(profile, brand) assembles/trims the outbound
  userProfile (measurements, brandSizes, brandConfidence, feedbackHistory selection).
- backend/ai/fitRecommend.js — buildUserPrompt() and its helpers buildBrandContext(),
  buildKnownBrandSizes(), buildCommunityContext() consume those fields into the GPT prompt.
Scoring: both the frontend payload builder and the backend prompt builders.
-->

### F3
Request: Right now an un-reviewed size prompt stops nagging the shopper after a
fixed number of days (it drops off the badge and the nudges). We want to change
that cutoff — and heads up, the same threshold is enforced in more than one
place, so a single edit won't be enough. Where does it live?

<!--
GROUND TRUTH (pattern: commit 5ecbeea "21-day expiry" + cecda12 scheduler)
CROSS-LAYER / DUPLICATED CONSTANT. Files:
- frontend/src/utils/time.js — PENDING_EXPIRY_DAYS (= 21) and isPendingExpired().
- frontend/src/hooks/useRecommendations.js — `pending` filter applies isPendingExpired.
- backend/utils/fitCheckScheduler.js — EXPIRY_DAYS (= 21, "kept in lockstep with frontend")
  bounding the nudge-eligibility window.
Scoring: full credit requires naming BOTH the frontend constant and the backend scheduler copy.
-->

### F4
Request: We're adding a brand-new API route that costs money to serve, and we
want it locked down the same way the others are — only signed-in users may call
it, and a single caller can't hammer it. Where are those two protections
defined, and where are they attached to routes?

<!--
GROUND TRUTH (pattern: commit f9aaf3c "Firebase auth + rate limiting on the whole /api surface")
BACKEND. Files:
- backend/middleware/auth.js — requireUser() (Firebase ID-token verification; monitor/enforce modes).
- backend/middleware/rateLimit.js — the limiter() factory + exported limiters (recommendLimiter,
  inferLimiter, pushSendLimiter, pushFeedbackLimiter), keyed by uid→IP.
- backend/index.js — the mount order: app.use('/api', requireUser) then per-path limiters then routers.
Scoring: auth.js + rateLimit.js + the index.js wiring.
-->

### F5
Request: We want to support another shopping site. On this one the brand name
isn't the web address itself — it sits inside the path of the product link
(the way marketplace listings put the seller/brand in the URL). Where do we add
the parsing rule, and is it in one place or more?

<!--
GROUND TRUTH (pattern: existing myntra/ajio/flipkart branches; commits 24a74bc, 3152b59)
DUPLICATED FRONTEND+BACKEND. Files:
- frontend/src/utils/brandExtractor.js AND backend/utils/brandExtractor.js — extractBrandFromUrl(),
  the "MARKETPLACE SITES" section that splits the pathname and picks the brand segment
  (hostname.includes('myntra.com') / 'ajio.com' / 'flipkart.com' branches).
Scoring: extractBrandFromUrl marketplace path-parsing; bonus for noting the logic is
duplicated across the frontend and backend copies and must be changed in both.
-->

### F6 (prospective — feature not yet built)
Request: We want to put signed-in usage behind a trial. After a handful of free
size recommendations, a shopper should be blocked from getting more until they
enter an unlock code that lifts the limit for their account permanently. The
cap and the code check both have to be tamper-proof (a user clearing their
browser storage must not reset their free count). Where would this feature plug
into the current code — both the enforcement point that must live server-side,
and the places the client needs to change?

<!--
GROUND TRUTH (PROSPECTIVE — no implementing commit; expected integration points in the
current codebase. Score as "found the right places to build it," partial credit per site.)
Server-side enforcement (the load-bearing part — must be here, not the client):
- backend/routes/recommend.js — the /api/recommend handler is where the paid AI call is
  spent; the per-user usage check + increment belongs before getRecommendation() runs.
  (backend/routes/infer.js optionally too.)
- backend/middleware/auth.js — requireUser() already sets the verified req.uid to key the
  counter/flag on; the gate relies on this identity, not a client-supplied id.
- backend/utils/firebaseAdmin.js — getDb() is the server's credentialed Firestore handle for
  reading/writing the per-user usage count + an `unlimited` flag + a coupons collection
  (atomic increment / transaction to avoid races). NOTE: this uses a NAMED admin app distinct
  from the auth middleware's credential-less app — a correct answer should reuse getDb().
- A new coupon-redemption route (would sit alongside the others in backend/, wired in
  backend/index.js behind requireUser + a rate limiter from backend/middleware/rateLimit.js).
Client side:
- frontend/src/pages/Home.jsx — submit() is where a recommendation is requested; it must
  handle the "limit reached" response and surface the unlock prompt instead of a generic error.
- frontend/src/utils/api.js — fetchRecommendation()/authHeaders() (the call already carries the
  ID token; would need to react to a 402/403 limit response).
- frontend/src/pages/Profile.jsx — natural home for the coupon-entry UI + remaining-uses display.
- frontend/src/utils/firestore.js — where user-doc reads/writes live (syncUserDoc/saveProfile);
  a client mirror of the usage count / unlimited flag would read through here.
Discriminators: (1) does the tool put the ENFORCEMENT server-side (recommend route) rather than
only client-side? (2) does it identify the coupon store + redemption as server-validated, not a
hardcoded client string?
-->

---

<!--
AUTHORING NOTES (graders only)
- No genuine TODO/FIXME/HACK markers exist in application code; the only matches are in
  docs/project.md (a planning log), so no "find the TODO" task was included.
- Debugging tasks were derived from real fix commits: 26a34bc, 3152b59/24a74bc, bda9921
  (+a72d386/25a4d32/dd6702e), 49b3485, a6dd37e.
- Feature tasks mirror real change patterns: 3bb37c3 (fit intent), 72bcb70 (payload trim),
  5ecbeea/cecda12 (expiry), f9aaf3c (auth + rate limit), 24a74bc (brand parsing).
- brandExtractor.js and the 21-day expiry constant are deliberately duplicated across
  layers — good discriminators for whether a tool finds ALL sites of a change, not just one.
-->
