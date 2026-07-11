"""Behavioral oracle for Hyperion — SEMANTIC-EQUIVALENCE (run-equivalence).

Hyperion (billythegoat356/Hyperion) is a Python *source obfuscator*. Its output uses
randomly-generated identifier names and a randomized transform pipeline, so asserting on
the exact obfuscated *text* (as an earlier version of this oracle did) is FLAKY — the same
input yields different output on every call, and Hyperion occasionally emits a broken
program. That flakiness made the docker build non-deterministic (the Dockerfile runs this
suite at build time).

This oracle instead asserts a DETERMINISTIC invariant: the obfuscated program, when
EXECUTED, produces the SAME stdout as the original program (semantic equivalence), AND the
obfuscated source is DIFFERENT from the input. That invariant holds regardless of which
random names Hyperion picks.

Determinism
-----------
Hyperion draws all of its randomness from the stdlib ``random`` module, so calling
``random.seed(SEED)`` before an obfuscation makes the transform byte-reproducible. Because
Hyperion still emits a broken program for *some* seeds, each known-answer test iterates a
fixed list of candidate seeds (always in the same order) and uses the first seed that yields
a runnable, output-equivalent, DIFFERING program. Every seed's obfuscation is byte-identical
across runs and its execution is invariant to ``PYTHONHASHSEED``, so the chosen seed — and
therefore pass/fail — is fully deterministic (never flaky).

Anti-reward-hack
----------------
A neutered Hyperion is caught two ways, both required for a test to pass:
  * ``obfuscate()`` that returns the input unchanged  -> the "output differs" check rejects
    every candidate seed, so the loop exhausts and the test FAILS.
  * ``obfuscate()`` that returns garbage / empty / non-runnable code -> the run-equivalence
    check (same stdout as the original) rejects every candidate seed -> the test FAILS.
"""
import io
import os
import sys
import random
import subprocess
import contextlib

import pytest

# Imported with the instrumentation / PYTHONPATH set by mayhem/build.sh + the Dockerfile ENV.
import hyperion


# Fixed, ordered candidate seeds. ~97% of seeds yield a working obfuscation, so in practice
# the first (seed 0) is chosen every time; the list only matters if a given environment's
# seed 0 happens to produce one of Hyperion's occasional broken outputs.
CANDIDATE_SEEDS = list(range(0, 64))

# The interpreter running this suite (in the commit image, the build-time python) is used to
# execute both the original and the obfuscated program, so they share a runtime.
PY = sys.executable


@contextlib.contextmanager
def _nostdout():
    """Suppress Hyperion's progress prints during obfuscation."""
    save_out, save_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    try:
        yield
    finally:
        sys.stdout, sys.stderr = save_out, save_err


def _obfuscate(src, seed, **kwargs):
    """Seed the RNG, then obfuscate ``src`` via the same API the fuzz harness exercises."""
    random.seed(seed)
    with _nostdout():
        h = hyperion.Hyperion(src, **kwargs)
    return h.content


def _run(code):
    """Execute a Python program in a subprocess; return (returncode, stdout).

    PYTHONHASHSEED is pinned so execution is reproducible independent of the obfuscation.
    """
    env = dict(os.environ, PYTHONHASHSEED="0")
    proc = subprocess.run(
        [PY, "-c", code], capture_output=True, text=True, timeout=120, env=env
    )
    return proc.returncode, proc.stdout


def obfuscate_equivalent(src, **kwargs):
    """Obfuscate ``src`` and assert SEMANTIC EQUIVALENCE.

    Returns the obfuscated source of the first candidate seed whose obfuscation
      (a) differs from the input (catches a no-op obfuscator), AND
      (b) runs to the SAME returncode + stdout as the input (catches a broken/garbage one).
    Fails the test if NO candidate seed satisfies both — i.e. the obfuscator is neutered.
    """
    exp_rc, exp_out = _run(src)
    assert exp_rc == 0, f"KAT input must itself run cleanly, got rc={exp_rc}"

    saw_differing = False
    for seed in CANDIDATE_SEEDS:
        obf = _obfuscate(src, seed, **kwargs)
        assert isinstance(obf, str) and obf, f".content must be a non-empty str (seed {seed})"
        if obf == src:
            # No-op obfuscation — a neutered obfuscator hits this for every seed.
            continue
        saw_differing = True
        rc, out = _run(obf)
        if rc == exp_rc and out == exp_out:
            # Sanity: the obfuscation really did transform the source (defends against a
            # no-op obfuscator whose output only trivially differs by whitespace).
            assert obf.strip() != src.strip(), "obfuscated output is a whitespace-only change"
            return obf

    if not saw_differing:
        pytest.fail(
            "Hyperion returned the input UNCHANGED for every candidate seed — a real "
            "obfuscator must transform its input (neutered/no-op obfuscator detected)."
        )
    pytest.fail(
        "no candidate seed produced an obfuscation that runs equivalently to the input "
        f"(expected stdout {exp_out!r}); Hyperion is producing broken/non-equivalent output."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Known-answer run-equivalence tests: obfuscate(src) must EXECUTE like src.
# ──────────────────────────────────────────────────────────────────────────────

def test_run_equivalence_arithmetic():
    """Obfuscating arithmetic preserves its computed output (6*7 -> 42, etc.)."""
    src = "print(6 * 7)\nprint(sum(range(10)))\n"  # -> "42\n45\n"
    obf = obfuscate_equivalent(src)
    assert obf != src


def test_run_equivalence_loop_and_function():
    """A loop + function-call program obfuscates to an equivalent program."""
    src = (
        "def square(n):\n"
        "    return n * n\n"
        "total = 0\n"
        "for i in range(5):\n"
        "    total += square(i)\n"
        "print(total)\n"  # 0+1+4+9+16 = 30
    )
    obf = obfuscate_equivalent(src)
    assert obf != src


def test_run_equivalence_string_ops():
    """String manipulation is preserved through obfuscation."""
    src = "s = 'hyperion'\nprint(s.upper())\nprint(s[::-1])\nprint(len(s) * 3)\n"
    obf = obfuscate_equivalent(src)
    assert obf != src


def test_run_equivalence_ultrasafemode():
    """ultrasafemode (documented 'skip the riskiest layers' path) is also run-equivalent."""
    src = "print(6 * 7)\nprint('ok' if 2 > 1 else 'no')\n"
    obf = obfuscate_equivalent(src, ultrasafemode=True)
    assert obf != src


def test_obfuscation_is_not_a_no_op():
    """The obfuscated output must differ from the input (explicit no-op guard)."""
    src = 'print("hello world")'
    obf = _obfuscate(src, CANDIDATE_SEEDS[0])
    assert obf != src, "Hyperion must transform the input — output must differ from input"


# ──────────────────────────────────────────────────────────────────────────────
# Deterministic non-text invariants (no exact-output assertions).
# ──────────────────────────────────────────────────────────────────────────────

def test_content_attribute_is_nonempty_string():
    """Hyperion must populate .content with a non-empty string."""
    h = _obfuscate_obj("a = 1", CANDIDATE_SEEDS[0])
    assert isinstance(h.content, str), f".content must be str, got {type(h.content)}"
    assert len(h.content) > 0, ".content must be non-empty"


def test_tokenize_error_on_unclosed_string():
    """An unclosed string literal is handled as a known exception, not an uncaught crash."""
    from tokenize import TokenError
    try:
        with _nostdout():
            random.seed(CANDIDATE_SEEDS[0])
            hyperion.Hyperion('x = "unclosed string literal')
    except (TokenError, AttributeError, UnboundLocalError):
        pass  # known-expected — the fuzz harness catches exactly these.


def test_empty_string_does_not_crash():
    """Empty input is handled without an uncaught (non-known) exception."""
    from tokenize import TokenError
    try:
        h = _obfuscate_obj("", CANDIDATE_SEEDS[0])
        assert isinstance(h.content, str)
    except (TokenError, AttributeError, UnboundLocalError):
        pass  # known-expected per the harness contract.


def _obfuscate_obj(src, seed, **kwargs):
    """Like _obfuscate but returns the Hyperion instance (for .content introspection)."""
    random.seed(seed)
    with _nostdout():
        return hyperion.Hyperion(src, **kwargs)
