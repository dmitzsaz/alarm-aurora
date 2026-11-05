#!/bin/bash
# Creates a disposable ARM64 Ubuntu build environment. No host package installs.
set -euo pipefail
if (( $# != 1 )) || [[ $(uname -m) != aarch64 ]]; then
  echo "Usage (as root on aarch64 Linux): $0 NEW_BUILD_CHROOT" >&2
  exit 2
fi
root=$(realpath -m "$1")
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ -d $root ]]; then
  [[ -f $root/.aurora-fex-build-chroot ]] || { echo 'Existing unmarked directory refused' >&2; exit 1; }
else
  mkdir -p "$root"
  touch "$root/.aurora-fex-build-chroot"
fi
if [[ ! -e $root/etc/os-release ]]; then
  archive=$root/../ubuntu-base-24.04.5-arm64.tar.gz
  [[ -f $archive ]] || curl -fL --retry 3 \
    https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.5-base-arm64.tar.gz -o "$archive"
  printf '%s  %s\n' a91d5a93010193712d346d761372b7c9db6dfcf093893161c64ca107f05914f2 "$archive" | sha256sum -c -
  tar xzf "$archive" -C "$root"
fi
cp -L /etc/resolv.conf "$root/etc/resolv.conf"
printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
chmod +x "$root/usr/sbin/policy-rc.d"
rm -f "$root/etc/apt/sources.list.d/ubuntu.sources"
cat > "$root/etc/apt/sources.list" <<'SOURCES'
deb [arch=arm64] http://ports.ubuntu.com/ubuntu-ports noble main universe
deb [arch=arm64] http://ports.ubuntu.com/ubuntu-ports noble-updates main universe
deb [arch=arm64] http://ports.ubuntu.com/ubuntu-ports noble-security main universe
deb [arch=amd64,i386] http://archive.ubuntu.com/ubuntu noble main universe
deb [arch=amd64,i386] http://archive.ubuntu.com/ubuntu noble-updates main universe
deb [arch=amd64,i386] http://security.ubuntu.com/ubuntu noble-security main universe
SOURCES
cp "$script_dir/ubuntu-build-deps.txt" "$root/opt/"
# Mounts disappear with this namespace, including on a failed apt transaction.
unshare -m --propagation private /bin/bash -s -- "$root" <<'CHROOT'
set -euo pipefail
root=$1
mount -t proc proc "$root/proc"
mount --rbind /dev "$root/dev"
chroot "$root" /usr/bin/env DEBIAN_FRONTEND=noninteractive /bin/bash -s <<'APT'
set -euo pipefail
dpkg --add-architecture amd64
dpkg --add-architecture i386
apt-get update
mapfile -t deps < /opt/ubuntu-build-deps.txt
apt-get install -y --no-install-recommends "${deps[@]}"
python3 -m venv /opt/meson --system-site-packages
/opt/meson/bin/pip install meson==1.10.1
apt-get clean
APT
CHROOT
