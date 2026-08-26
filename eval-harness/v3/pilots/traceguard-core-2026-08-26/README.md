# TraceGuard Core plan-v1 smoke run

This directory contains the immutable plan-v1 deterministic comparison for
RKA experiment `exp_01M1028QK2VP6NC1XNC6WJBE0Y`. It uses only Python's
standard library and inert symbolic features; it does not contact services or
contain operational payloads, credentials, personal data, or victim data.

Run from this directory:

```text
python3 -m unittest -v test_traceguard_smoke.py
python3 traceguard_smoke.py --output-dir artifacts
```

The generated manifest freezes seed `20260826`, plan version `1`, exact class
counts and detector/metric definitions. Overall accuracy is only a smoke-test
summary; delayed-attack recall and benign false-positive rate remain separate.
