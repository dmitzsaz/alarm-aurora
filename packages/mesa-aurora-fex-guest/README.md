# FEX guest Mesa

`PKGBUILD` builds the distro's x86_64/i686 layer on x86_64 Arch. Its source
pin/version deliberately follows `mesa-aurora` and `sources.json`. It installs
through `aurora-fex-mesa.service` over the distro-provided guest base. Do not
copy this Arch-linked payload into an Ubuntu rootfs: glibc and other runtime
libraries need not be compatible.

## J704 with an Ubuntu 24.04 directory rootfs

Build the **installed host's exact source**, including its Asahi UAPI and GPU
compiler. The J704 `mesa-j704 1:26.3.0_devel.df0e691-1` baseline uses
`df0e691a15a8550c08e2e09f69e5942c99e0a3f5`, not the distro recipe's pin.
The scripts here provide a separate Ubuntu-compatible build without changing
the distro's synchronized source pins or installing host packages.

This follows the principle of independently maintained guest graphics layers.
[Asahi's rootfs generator](https://github.com/AsahiLinux/fex-emu-rootfs-generator/blob/main/src/main.rs)
composes rootfs layers with overlayfs; MUVM also supports `-f BASE -f LAYER`
for EROFS images. For an existing writable Ubuntu directory, a versioned
`/opt` prefix is simpler: no mounts, apt file replacements, diversions,
systemd service, or global FEX configuration. Selection is explicit per
application. This prefix/wrapper is an adaptation for this installation, not
an upstream Fedora rootfs package.

### Build on aarch64 Linux

Use the J704 or a local ARM Linux VM with bash, curl, GNU coreutils, tar,
unshare/mount/chroot, and sufficient disk space. The helper creates a separate
Ubuntu build chroot and installs all build packages **there**. Never point it
at the user's FEX rootfs. It refuses existing unmarked directories.

Export the Mesa commit from the Mac without including working-tree changes:

```sh
commit=df0e691a15a8550c08e2e09f69e5942c99e0a3f5
git -C /Users/zsaz/Desktop/linux-m5/mesa archive --format=tar --prefix=mesa/ "$commit" |
  gzip -1 > mesa-df0e691.tar.gz
```

Copy that archive and this recipe directory to the chosen aarch64 build
machine. The remaining commands run as root on that Linux machine:

```sh
build=/home/nugget/build/fex-guest-mesa-df0e691
recipe=$build/recipe
commit=df0e691a15a8550c08e2e09f69e5942c99e0a3f5
prefix=/opt/aurora-fex-mesa/df0e691a15
nice -n 19 ionice -c3 "$recipe/prepare-ubuntu-chroot.sh" "$build/chroot"
mkdir -p "$build/chroot/work"
tar xzf "$build/mesa-df0e691.tar.gz" -C "$build/chroot/work"
cp -a "$recipe" "$build/chroot/opt/recipe"
nice -n 19 ionice -c3 unshare -m --propagation private bash -s -- "$build/chroot" "$prefix" "$commit" <<'BUILD'
set -euo pipefail
root=$1; prefix=$2; commit=$3
mount -t proc proc "$root/proc"
mount --rbind /dev "$root/dev"
chroot "$root" /usr/bin/env \
  PATH=/opt/meson/bin:/usr/lib/llvm-18/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  MESA_FEX_JOBS=2 /opt/recipe/build-ubuntu-multiarch.sh \
  /work/mesa /work/build /work/stage "$prefix" "$commit"
BUILD
python3 "$recipe/check-ubuntu-prefix.py" "$build/chroot/work/stage" "$prefix"
```

The build uses native LLVM 18 shader generators from the same source and GCC
13 cross compilers for the drivers. Both target runtimes disable LLVM and
SPIRV-Tools linkage. Gallium includes `asahi`, `zink`, and `softpipe`; Vulkan
includes Asahi with its virtio native-context backend. Each architecture gets
its own ICD with an absolute library path and `library_arch`. Runtime ABI
checks reject libraries requiring glibc newer than Ubuntu 24.04's 2.39.

### Install and use

```sh
rootfs=/home/nugget/.local/share/fex-emu/RootFS/Ubuntu_24_04
prefix=/opt/aurora-fex-mesa/df0e691a15
"$recipe/install-ubuntu-prefix.sh" "$build/chroot/work/stage" "$rootfs" "$prefix"
```

The installer copies only the new prefix and refuses to overwrite an existing
version. Kisak's `/usr` files and dpkg records remain intact; apt does not own
the `/opt/aurora-fex-mesa` files. Retain the staged tree or archive for reinstall.

Run `with-mesa` **inside the x86 shell**. Do not export its `LD_LIBRARY_PATH`
or `VK_DRIVER_FILES` on the outer ARM MUVM process: libkrun's renderer needs
native ARM libraries. A fresh, isolated instance, run as `nugget`:

```sh
rootfs=/home/nugget/.local/share/fex-emu/RootFS/Ubuntu_24_04
runtime=$(mktemp -d /run/user/1000/muvm-fex-mesa.XXXXXXXX)
# On desktops with X authentication, use the current /run/user/1000/xauth_*.
# The tested Xwayland session had no -auth argument and needed no XAUTHORITY.
DISPLAY=:0 XDG_RUNTIME_DIR="$runtime" ASAHI_M5_BRINGUP=1 \
MESA_LOADER_DRIVER_OVERRIDE=zink \
muvm --emu=fex --mem=4096 --vram=2048 \
  -e ASAHI_M5_BRINGUP=1 -e MESA_LOADER_DRIVER_OVERRIDE=zink -- \
  "$rootfs/usr/bin/bash" /opt/aurora-fex-mesa/df0e691a15/bin/with-mesa \
  /usr/bin/vulkaninfo --summary
rm -rf -- "$runtime"
```

Replace the last command with `/usr/bin/vkcube --c 10`,
`/usr/bin/glxinfo -B`, or a 32-bit application. Keep each independent MUVM
instance's runtime separate. The wrapper sets the two architecture library
and DRI paths, both ICD manifests, Mesa's EGL vendor manifest, and Zink.
It does not modify Wine prefixes, WinBox's app configuration, or default
launchers. Existing launches remain opt-out until explicitly wrapped.

### Rollback

Exit only applications you launched with this prefix. Normal unwrapped
launches already use the original drivers. Remove the isolated prefix:

```sh
rm -rf -- /home/nugget/.local/share/fex-emu/RootFS/Ubuntu_24_04/opt/aurora-fex-mesa/df0e691a15
```

No apt reinstall, dpkg-divert reversal, host package rollback, service restart,
or FEX configuration edit is needed. Do not delete the prefix while an
application still uses it. Rebuild and requalify the guest when the host Mesa
source or experimental GPU UAPI changes.

## Hardware validation

On 2026-11-05, with the J704's `mesa-j704` at the commit above and
`virglrenderer-aurora 1.3.0-1`, a fresh `muvm --emu=fex` passed x86_64
`vulkaninfo --summary`, ten-frame Vulkan cubes in both architectures, and
x86_64/i686 Zink GL 4.6 queries. Both GL queries reported
`26.3.0-devel (git-df0e691a15)` and `AURORA_BOREALIS`. The host kernel log
had no new messages across the tests. The old Ubuntu Vulkan tool prints
`UNKNOWN_VkDriverId_value35`, but correctly reports `driverName = Borealis`
and the matching Mesa commit; loader diagnostics confirm the `/opt` ICD.
Original Kisak libraries, dpkg status, FEX configuration, and WinBox app
configuration retained their hashes. Wine and WinBox were not relaunched.
