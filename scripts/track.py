"""Legacy shim. Prefer: ``pl-winner track <op>``."""
from __future__ import annotations
import sys
from pl_winner.cli import main
if __name__ == "__main__":
    raise SystemExit(main(["track", *sys.argv[1:]]))
