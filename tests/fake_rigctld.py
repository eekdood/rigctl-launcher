#!/usr/bin/env python3
"""Fake daemon: loopback socket and output only, never touches a serial device."""
import argparse
import signal
import socket
import sys
import time

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('-t', type=int, required=True)
parser.add_argument('-T', default='127.0.0.1')
parser.add_argument('--fake-mode', default='normal')
args, rest = parser.parse_known_args()
print('fake arguments: ' + repr(sys.argv[1:]), flush=True)
print('fake stderr ready', file=sys.stderr, flush=True)
if args.fake_mode == 'fail':
    print('simulated startup failure', file=sys.stderr, flush=True)
    raise SystemExit(7)
if args.fake_mode == 'stubborn':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if args.fake_mode == 'flood':
    sys.stdout.write('x' * 350_000)
    sys.stdout.flush()
with socket.socket() as sock:
    sock.bind((args.T, args.t))
    sock.listen()
    print(f'fake listening at {args.T}:{args.t}', flush=True)
    while True:
        time.sleep(0.03)
