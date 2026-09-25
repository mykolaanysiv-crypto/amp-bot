"""Start the canonical AMP web and worker processes locally on all platforms."""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    children: list[subprocess.Popen] = []

    def stop_on_term(signum, frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_term)
    try:
        children.append(subprocess.Popen([sys.executable, 'run_web.py'], cwd=ROOT))
        children.append(subprocess.Popen([sys.executable, 'run.py'], cwd=ROOT))
        while all(child.poll() is None for child in children):
            time.sleep(1)
        print('An AMP process stopped; shutting down the other.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
