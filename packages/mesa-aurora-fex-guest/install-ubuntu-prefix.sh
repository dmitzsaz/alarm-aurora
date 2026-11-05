#!/bin/bash
# Copy only a new /opt prefix. No apt, diversions, mounts or FEX config changes.
set -euo pipefail
if (( $# != 3 )); then
  echo "Usage: $0 STAGE ROOTFS /opt/aurora-fex-mesa/VERSION" >&2
  exit 2
fi
stage=$(realpath "$1")
rootfs=$(realpath "$2")
prefix=$3
[[ $prefix =~ ^/opt/aurora-fex-mesa/[a-zA-Z0-9._-]+$ ]] || { echo 'Invalid prefix' >&2; exit 1; }
[[ -f $rootfs/var/lib/dpkg/status && -d $rootfs/usr/lib/i386-linux-gnu ]] || {
  echo 'Expected an Ubuntu multiarch directory rootfs' >&2; exit 1;
}
[[ -s $stage$prefix/.aurora-mesa-commit && -x $stage$prefix/bin/with-mesa ]] || {
  echo 'Incomplete guest layer' >&2; exit 1;
}
for arch in x86_64 i686; do
  libdir=x86_64-linux-gnu; elfclass=ELF64
  [[ $arch != i686 ]] || { libdir=i386-linux-gnu; elfclass=ELF32; }
  readelf -h "$stage$prefix/lib/$libdir/libvulkan_asahi.so" | grep -q "Class:.*$elfclass"
  [[ -s $stage$prefix/share/vulkan/icd.d/asahi_icd.$arch.json ]]
done
[[ ! -e $rootfs$prefix && ! -L $rootfs$prefix ]] || {
  echo "Already exists; use a new version or explicitly roll back first: $rootfs$prefix" >&2; exit 1;
}
parent=$rootfs/opt/aurora-fex-mesa
# Refuse redirects outside the specified rootfs.
for path in "$rootfs/opt" "$parent"; do
  [[ ! -L $path ]] || { echo "Symlink refused: $path" >&2; exit 1; }
done
mkdir -p "$parent"
tmp=$(mktemp -d "$parent/.install.XXXXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
cp -a "$stage$prefix/." "$tmp/"
mv -T -- "$tmp" "$rootfs$prefix"
trap - EXIT
printf 'Installed %s\n' "$rootfs$prefix"
printf 'Enable inside FEX: %s/bin/with-mesa COMMAND [ARGS...]\n' "$prefix"
printf 'Rollback after exiting applications using it: rm -rf -- %q\n' "$rootfs$prefix"
