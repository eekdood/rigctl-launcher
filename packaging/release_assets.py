"""Create the public release layout from the three native CI artifacts."""
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_support.inventory import project_version
from build_support.naming import checkout_identity
from build_support.release_assets import prepare_release
from build_support.versioning import artifact_output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    version = project_version(ROOT)
    identity = checkout_identity(ROOT, version)
    for name in prepare_release(args.inputs, args.output, version, identity=identity):
        print(name)
    artifact_output(f'rigctl-launcher_{identity["name"]}_downloads')
