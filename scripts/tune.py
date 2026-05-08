"""Legacy shim. Prefer: ``pl-winner tune``."""
from __future__ import annotations
import sys
from pl_winner.cli import main
if __name__ == "__main__":
    raise SystemExit(main(["tune", *sys.argv[1:]]))
