import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not getattr(sys, "frozen", False) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mtcodec.viewer import open_path


def pick_file():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="打开 MTB / MTC 文件",
        filetypes=[("MTB / MTC", "*.mtb *.mtc"), ("所有文件", "*.*")],
    )
    root.destroy()
    return path


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        return open_path(args[0])
    path = pick_file()
    if not path:
        return 0
    return open_path(path)


if __name__ == "__main__":
    sys.exit(main())
