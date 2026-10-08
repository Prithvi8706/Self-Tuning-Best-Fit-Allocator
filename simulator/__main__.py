"""Command line: python -m simulator [--host 127.0.0.1] [--port 8000]"""
import argparse
import sys

from simulator.server import serve


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m simulator", description="Serve the ARBF simulator UI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
