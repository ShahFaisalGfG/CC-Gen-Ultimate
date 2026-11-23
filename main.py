# main.py - `python main.py ...` runs the command line (ccgen/cli.py), as it did before the package had it

import sys

from ccgen.cli import main

if __name__ == "__main__":
    sys.exit(main())
