#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print 'Run the setup instructions in readme.md first.'
  exit 1
fi
exec .venv/bin/python -m rigctl_launcher
