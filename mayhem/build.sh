#!/usr/bin/env bash
#
# mayhem/build.sh — build the Hyperion Atheris fuzz harness + its standalone reproducer,
# and prepare the project's own pytest oracle. Runs inside the commit image (mayhem/Dockerfile)
# as `mayhem` in /mayhem. Python adaptation of the C/C++ template.
#
# What it does (must be idempotent + air-gapped on re-run — SPEC §6.2 item 9 / §6.5):
#   1. Populate / reuse an in-image wheelhouse under /opt/toolchains/python (HOME-independent),
#      then install atheris + pytest + pystyle OFFLINE from that wheelhouse into a fixed
#      site dir on PYTHONPATH. The first (CI, online) build fills the wheelhouse; the air-gapped
#      PATCH re-run resolves entirely from it (pip --no-index --find-links). hyperion itself
#      stays the editable source tree (hyperion.py at repo root, added to PYTHONPATH) so a
#      PATCH agent's edits take effect.
#   2. Compile launcher.c -> the ELF Mayhem target `hyperion_fuzzer` (Atheris is a Python script;
#      Mayhem needs an ELF cmd, and the gate needs DWARF < 4 — hence a compiled wrapper).
#   3. Build the same launcher as the standalone (run-once) reproducer `hyperion_fuzzer-standalone`.
#   4. Compile the run_tests.c ELF wrapper so the pytest oracle runs through a NON-system binary
#      (so the gate's sabotage check bites it).
#
# The base image exports the build contract (CC, SANITIZER_FLAGS, DEBUG_FLAGS, ...). We only need
# DEBUG_FLAGS here (the launcher is a thin C exec wrapper — sanitizing it would just instrument the
# wrapper, not the fuzzed Python; Atheris instruments the Python library itself at import time).
set -euo pipefail

[ -n "${SOURCE_DATE_EPOCH:-}" ] || unset SOURCE_DATE_EPOCH

: "${DEBUG_FLAGS:=-g -gdwarf-3}"
: "${CC:=clang}"
: "${MAYHEM_JOBS:=$(nproc)}"
export DEBUG_FLAGS CC MAYHEM_JOBS

SRC="${SRC:-/mayhem}"
cd "$SRC"

# ── Python toolchain caches at a FIXED, $HOME-independent prefix (SPEC §6.2 item 8) ──
PY_PREFIX=/opt/toolchains/python
WHEELHOUSE="$PY_PREFIX/wheelhouse"
SITE="$PY_PREFIX/site"
mkdir -p "$WHEELHOUSE" "$SITE"

PY="$(command -v python3)"

# 1) Wheelhouse: download every runtime/test dependency ONCE (online). On the air-gapped re-run the
#    directory is already populated, so pip never reaches the network. atheris ships a prebuilt
#    manylinux wheel for this CPython; pytest is the oracle runner; pystyle is hyperion's runtime
#    dep. hyperion.py is pure-Python and stays the editable source tree (no install needed).
PKGS=(atheris pytest pystyle)
need_download=0
"$PY" -c "import os,glob,sys; sys.exit(0 if glob.glob(os.path.join('$WHEELHOUSE','atheris-*.whl')) else 1)" || need_download=1
if [ "$need_download" -eq 1 ]; then
  echo ">> populating wheelhouse (online) at $WHEELHOUSE"
  "$PY" -m pip download --dest "$WHEELHOUSE" "${PKGS[@]}"
else
  echo ">> wheelhouse already populated — reusing $WHEELHOUSE (air-gapped re-run path)"
fi

# 2) Install the deps into the fixed site dir, OFFLINE from the wheelhouse. --no-index +
#    --find-links guarantees no PyPI access (works on the air-gapped re-run). Guarded to be
#    idempotent: once the site dir holds atheris+pytest+pystyle we SKIP the reinstall.
if "$PY" -c "import os,glob,sys; sys.exit(0 if (glob.glob(os.path.join('$SITE','atheris*')) and glob.glob(os.path.join('$SITE','pytest*')) and glob.glob(os.path.join('$SITE','pystyle*'))) else 1)"; then
  echo ">> deps already installed in $SITE — skipping (idempotent re-run)"
else
  echo ">> installing deps (offline) into $SITE"
  "$PY" -m pip install --no-index --find-links="$WHEELHOUSE" --target "$SITE" "${PKGS[@]}"
fi

# hyperion itself: flat layout (hyperion.py at the repo root), so expose it by putting $SRC
# on PYTHONPATH — both via the baked ENV in the Dockerfile (run time) and via env.sh /
# the explicit sanity check below (build time).
PYRUN="$SITE:$SRC"

# Record the site dir + interpreter for test.sh / the launcher to consume.
cat > "$PY_PREFIX/env.sh" <<EOF
export PYTHONPATH="$PYRUN\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHON_BIN="$PY"
EOF

# Sanity: the harness imports must resolve offline now.
PYTHONPATH="$PYRUN" "$PY" -c 'import atheris, pytest, pystyle, hyperion; print("imports OK")'

# 3) Compile the ELF launcher target + the standalone reproducer (DWARF < 4 via $DEBUG_FLAGS).
HARNESS="$SRC/mayhem/fuzz_obfuscator.py"
echo ">> compiling hyperion_fuzzer (+ standalone) with DEBUG_FLAGS=$DEBUG_FLAGS"
$CC $DEBUG_FLAGS -DPYTHON="\"$PY\"" -DHARNESS="\"$HARNESS\"" \
    "$SRC/mayhem/launcher.c" -o "$SRC/hyperion_fuzzer"
# The standalone reproducer uses the same launcher.
$CC $DEBUG_FLAGS -DPYTHON="\"$PY\"" -DHARNESS="\"$HARNESS\"" \
    "$SRC/mayhem/launcher.c" -o "$SRC/hyperion_fuzzer-standalone"

# 4) The pytest oracle runs through a compiled NON-system ELF wrapper so the gate's anti-reward-hack
#    sabotage check (which neuters non-system binaries to exit(0)) actually bites the suite.
$CC $DEBUG_FLAGS -DPYTHON="\"$PY\"" "$SRC/mayhem/run_tests.c" -o "$SRC/hyperion_run_tests"

echo ">> build.sh complete"
ls -la "$SRC/hyperion_fuzzer" "$SRC/hyperion_fuzzer-standalone" "$SRC/hyperion_run_tests"
