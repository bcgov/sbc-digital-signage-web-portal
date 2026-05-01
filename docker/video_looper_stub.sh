#!/bin/sh
set -eu

trap 'exit 0' INT TERM

while true; do
    sleep 3600
done
