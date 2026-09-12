"""Run the editor directly from a source checkout."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from icr2_3dedit.app import main  # noqa: E402


if __name__ == "__main__":
    main()

