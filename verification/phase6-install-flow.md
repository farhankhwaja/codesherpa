# Phase 6 — clean-venv install → init → claude mcp add (verified)

Date: 2026-07-04 · branch phase-6 (post D38-final/D39) · macOS, CPython 3.12.

Exact commands run, from nothing, in a scratch directory (venv OUTSIDE the
repo — see D38 for why the first attempt that placed .venv inside the clone
led to the memory investigation):

```bash
git clone --branch phase-6 <this-repo> repo
python3.12 -m venv venv                       # (uv venv --python 3.12 venv)
venv/bin/pip install -e "./repo"              # installs distribution `codesherpa`
cd repo
../venv/bin/sherpa init .
#   sherpa sync: indexing files 14/145 … 145/145
#   sherpa: first index: 145 blobs, 535 chunks, 145 files (0.42s)
#   sherpa: embedding 535 chunks (CPU; incremental …) 0% … 100%
#   → completed: 118.8 s wall, PEAK RSS 4.06 GB (/usr/bin/time -l), 535/535 embedded
claude mcp add sherpa -- "$PWD/../venv/bin/python" -m codesherpa.mcp_server "$PWD"
claude mcp list
#   sherpa: … -m codesherpa.mcp_server …  - ✔ Connected      ← real MCP handshake
```

Also exercised: `sherpa search "where does the incremental sync decide which
blobs are new"` → `codesherpa/gitlayer/sync.py` (module + `_sync_locked`
chunks) in the top results.

Notes:
- `init` on a repo that still has a pre-rename `.repograph/` directory
  prints a one-line "legacy index — safe to delete" warning (D38).
- First-ever run additionally downloads the embedding model (~0.5 GB) with
  a printed notice; this machine had it cached under `~/.cache/sherpa/`.
- The `claude mcp add` used `--scope local` during verification and was
  removed afterwards; the README documents the default (project-scope)
  command form.
