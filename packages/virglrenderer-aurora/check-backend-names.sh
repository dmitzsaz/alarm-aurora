#!/bin/sh
# Compile the actual dispatcher against a fake DRM device; no GPU is required.
set -eu
source_dir=${1:?Usage: check-backend-names.sh VIRGLRENDERER_SOURCE}
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
: > "$temporary/config.h"
: > "$temporary/xf86drm.h"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror \
  -I"$temporary" -I"$source_dir/src" \
  "$test_dir/backend-names.c" -o "$temporary/backend-names"
"$temporary/backend-names"
