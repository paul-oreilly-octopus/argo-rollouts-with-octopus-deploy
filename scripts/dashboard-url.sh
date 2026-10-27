#!/usr/bin/env bash
# Prints the dashboard's URL.
source "$(dirname "$0")/config.sh"
if [[ "$INGRESS_HTTP_PORT" == 80 ]]; then echo "http://colour-demo.localtest.me"; else echo "http://colour-demo.localtest.me:$INGRESS_HTTP_PORT"; fi
