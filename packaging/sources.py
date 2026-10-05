"""Generate matching source downloads after packaging/build.py."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_support.inventory import collected_entries
from build_support.notices import SourceCache
from build_support.sources import build_sources

if __name__ == '__main__':
    for path in sorted((ROOT / 'artifacts' / 'packages').glob('*.inventory.json')):
        report = json.loads(path.read_text())
        output = path.with_name(path.name.removesuffix('.inventory.json') + '-sources.tar.gz')
        build_sources(report, collected_entries(ROOT / 'build' / 'rigctl-launcher'), ROOT, output,
                      SourceCache(ROOT / 'build' / 'notice-cache'))
        print(f'Collected matching sources: {output.name}')
