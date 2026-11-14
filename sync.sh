#!/bin/sh
# Copy the local store into this repo. Usage: ./sync.sh <store-dir>
set -e
src="$1"
mkdir -p docs links
rsync -a --exclude manifest.jsonl --exclude attempts.jsonl --exclude held.csv "$src"/ docs/
cp "$src"/manifest.jsonl "$src"/attempts.jsonl "$src"/held.csv .
