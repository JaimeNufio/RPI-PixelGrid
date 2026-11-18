#!/usr/bin/env python3
"""Kept so older commands still work: same as `run.py --state snow ...`.

Defaults now come from config.json; see `run.py --help`.
"""
import sys

from run import main

if __name__ == "__main__":
    main(["--state", "snow", *sys.argv[1:]])
