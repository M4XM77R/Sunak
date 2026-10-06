#!/usr/bin/env python3
"""Start Sunak straight from the downloaded folder, without installing:

    python3 start.py          (Windows: double-click this file, or: py start.py)

Takes the same options and commands as `sunak`, e.g. `python3 start.py --port 8123` or `python3 start.py stop`."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sunak.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
