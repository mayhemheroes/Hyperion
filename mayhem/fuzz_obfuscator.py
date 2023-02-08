#! /usr/bin/env python3
from tokenize import TokenError

import atheris
import sys
import io
from contextlib import contextmanager

import fuzz_helpers

sys.path.append('../')  # This project is not distributed as an installable package
with atheris.instrument_imports(include=['hyperion']):
    import hyperion


# Disable stdout
@contextmanager
def nostdout():
    save_stdout = sys.stdout
    save_stderr = sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    yield
    sys.stdout = save_stdout
    sys.stderr = save_stderr

def TestOneInput(data):
    fdp = fuzz_helpers.EnhancedFuzzedDataProvider(data)
    try:
        with nostdout():
            hyperion.Hyperion(fdp.ConsumeRandomString(), fdp.ConsumeBool(), fdp.ConsumeBool(), fdp.ConsumeBool(),
                     fdp.ConsumeBool(), fdp.ConsumeBool(), fdp.ConsumeBool(), fdp.ConsumeBool(),
                     fdp.ConsumeBool(), fdp.ConsumeBool())
    except (UnboundLocalError, AttributeError, TokenError):
        return -1


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
