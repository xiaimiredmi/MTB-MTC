import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mtcodec.viewer import open_path

if len(sys.argv) < 2:
    raise SystemExit(2)
raise SystemExit(open_path(sys.argv[1]))
