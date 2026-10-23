"""Live integration check: print connection state, never authentication data."""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browser import ConnectionProblem, EdgeConnection


def main():
    connection = EdgeConnection(Path(os.environ["LOCALAPPDATA"]) / "CodexUsage" / "EdgeProfile")
    try:
        connection.start(visible=False)
        time.sleep(3)
        print("CDP connection established:", bool(connection.port))
        print("ChatGPT page available:", bool(connection._target()))
        try:
            usage, details = connection.fetch()
            print("Usage response received:", isinstance(usage, dict))
            print("Reset details received:", isinstance(details, dict))
        except ConnectionProblem as exc:
            print("Connection state:", str(exc))
            print("User login required:", exc.needs_login)
            if not exc.needs_login:
                raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
