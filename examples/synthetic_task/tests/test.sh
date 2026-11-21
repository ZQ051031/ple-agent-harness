#!/bin/sh
set -eu
mkdir -p /logs/verifier
printf '0' > /logs/verifier/reward.txt
python3 /tests/check.py
printf '1' > /logs/verifier/reward.txt
