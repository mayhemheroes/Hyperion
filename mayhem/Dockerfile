# Build Stage
FROM fuzzers/atheris:2.0.7-python3.9

ADD . /src
WORKDIR /src
RUN python3 -m pip install -U -r requirements.txt
WORKDIR /src/mayhem
CMD ["/src/mayhem/fuzz_obfuscator.py"]
