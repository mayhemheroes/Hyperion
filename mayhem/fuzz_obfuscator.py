#!/usr/bin/env python3
"""Atheris fuzz harness for the Hyperion Python obfuscator.

Feeds random bytes (interpreted as Python source code) into Hyperion's
obfuscation pipeline. The fuzz target is the tokenizer + transformer stack
inside hyperion.Hyperion — any unhandled exception (other than the known-expected
TokenError / AttributeError / UnboundLocalError) is surfaced as a crash.
"""
from tokenize import TokenError

import atheris
import sys
import io
from contextlib import contextmanager

# fuzz_helpers.py is in the same mayhem/ dir, on PYTHONPATH at /mayhem/mayhem/.
import fuzz_helpers

# Instrument hyperion imports so Atheris records coverage.
with atheris.instrument_imports(include=['hyperion']):
    import hyperion


@contextmanager
def nostdout():
    """Suppress Hyperion's progress prints."""
    save_stdout = sys.stdout
    save_stderr = sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = save_stdout
        sys.stderr = save_stderr


def TestOneInput(data):
    fdp = fuzz_helpers.EnhancedFuzzedDataProvider(data)
    try:
        with nostdout():
            hyperion.Hyperion(
                fdp.ConsumeRandomString(),
                fdp.ConsumeBool(),   # clean
                fdp.ConsumeBool(),   # obfcontent
                fdp.ConsumeBool(),   # renlibs
                fdp.ConsumeBool(),   # renvars
                fdp.ConsumeBool(),   # addbuiltins
                fdp.ConsumeBool(),   # randlines
                fdp.ConsumeBool(),   # shell
                fdp.ConsumeBool(),   # camouflate
                fdp.ConsumeBool(),   # safemode
            )
    except (UnboundLocalError, AttributeError, TokenError):
        # Known-expected exceptions for malformed / edge-case Python input.
        return -1


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
