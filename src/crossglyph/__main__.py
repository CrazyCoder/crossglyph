"""`python -m crossglyph`, which is what a background start runs.

The console script would do the same thing, except on Windows, where an
update replaces that `.exe` shim while it is running. A module inside the
package being started is not a file anything has to write over.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
