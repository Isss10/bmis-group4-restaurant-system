import sys
from pathlib import Path

# Allow running from repo root without installing the package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    # (保留原本的其他逻辑，这里只是确保导入不报错)
    pass


if __name__ == "__main__":
    sys.exit(main())
