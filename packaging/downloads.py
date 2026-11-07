"""Stage minimal application downloads without source or build sidecars."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_support.downloads import stage_downloads

if __name__ == '__main__':
    for name in stage_downloads(ROOT / 'artifacts' / 'builds', ROOT / 'artifacts' / 'downloads'):
        print(name)
