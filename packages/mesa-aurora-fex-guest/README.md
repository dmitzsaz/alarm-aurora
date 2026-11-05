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
or systemd service. The optional default selector below makes this layer the
user’s default for both FEX architectures through guest-only configuration.
This prefix/configuration is an adaptation for this writable Ubuntu rootfs,
not an upstream Fedora rootfs package.

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

### Make it the default for both FEX architectures

Run this once **as the FEX user**, after installing the prefix:

```sh
python3 "$recipe/set-fex-default.py" enable \
  "$HOME/.fex-emu/Config.json" "$rootfs" "$prefix"
```

Use the active configuration directory: this installation has the legacy
`~/.fex-emu`, which FEX prefers over `~/.config/fex-emu`. The selector verifies
`Config.RootFS`, both ELF architectures, ICD paths, and the EGL manifest. It
backs up every changed file under `mesa-default-backup.*` before activation,
preserves ownership/mode and unrelated settings, then prints its exact
one-command rollback. Repeating activation for the same prefix is a no-op.
Retain the helper at the printed path for rollback.

`Config.Env` selects the following **inside emulated processes only**:

- Both architecture library paths, DRI paths, and GBM backend paths.
- Only the two matching Asahi ICDs through `VK_DRIVER_FILES` and the older
  `VK_ICD_FILENAMES`; `library_arch` selects the correct ABI. Kisak's ICDs stay
  installed but are excluded from discovery, including after apt upgrades.
- Mesa's GLVND EGL manifest and GLX vendor, Zink, and M5 bring-up mode.

FEX's `Env` string list uses **repeated `"Env": "KEY=value"` object keys**,
not a JSON array. Generic JSON editors often silently discard all but the
last key. The helper reads/writes object pairs so existing repeated Env and
HostEnv settings survive. Existing AppConfig and pattern AppOverrides Env
lists receive the same selection, retaining unrelated environment variables.

GL/Vulkan thunks bypass guest Mesa, so the selector disables those two
entries in global `ThunksDB` and any existing user AppConfig that explicitly
sets them (including this machine's `WinBox.json`). Other thunks are retained.
Wine prefixes and application launchers are not edited. Future deliberate
AppConfig or launcher environment overrides can supersede these defaults;
re-run the selector after adding an AppConfig that changes graphics settings.

No `/usr` libraries, package manifests, dpkg state, loader cache, or native ARM
configuration is changed. apt owns neither this versioned prefix nor these
user FEX settings. This preserves the independently maintained graphics-layer
principle without installing hooks, diversions, or a rootfs mount overlay.
Keep the prefix installed while it is selected.

### Launch without a wrapper

Run as `nugget`, using a fresh runtime for each independent VM:

```sh
rootfs=/home/nugget/.local/share/fex-emu/RootFS/Ubuntu_24_04
runtime=$(mktemp -d /run/user/1000/muvm-fex-mesa.XXXXXXXX)
# If /run/user/1000/xauth_* exists, export XAUTHORITY to the current file.
DISPLAY=:0 XDG_RUNTIME_DIR="$runtime" ASAHI_M5_BRINGUP=1 \
MESA_LOADER_DRIVER_OVERRIDE=zink \
/usr/local/bin/muvm --emu=fex --mem=4096 --vram=2048 \
  -e ASAHI_M5_BRINGUP=1 -e MESA_LOADER_DRIVER_OVERRIDE=zink -- \
  "$rootfs/usr/bin/vkcube" --c 10
rm -rf -- "$runtime"
```

The rootfs path selects the **x86_64 executable**, with no shell or Mesa
wrapper. Replace it with `"$rootfs/usr/bin/glxinfo" -B`,
`"$rootfs/usr/bin/vulkaninfo" --summary`, an i686 executable, or Wine.
Normal Wine/WinBox/game launches automatically receive the new default when
FEX starts them. Never export these x86 library/ICD paths on the outer ARM
MUVM process: libkrun's renderer uses native ARM libraries.

On this machine `/usr/bin/vkcube` and `/usr/bin/glxinfo` are ARM64. The flag
`--emu=fex` registers the x86 interpreter; it does not turn native executables
into x86. Thus plain `muvm --emu=fex -- vkcube --c 10` with the usual PATH
still tests native Mesa. To exercise the plain command name with x86 Mesa,
put the rootfs bin directory first **in the VM's command lookup PATH**:

```sh
runtime=$(mktemp -d /run/user/1000/muvm-fex-mesa.XXXXXXXX)
DISPLAY=:0 XDG_RUNTIME_DIR="$runtime" ASAHI_M5_BRINGUP=1 \
MESA_LOADER_DRIVER_OVERRIDE=zink /usr/local/bin/muvm --emu=fex \
  -e ASAHI_M5_BRINGUP=1 -e MESA_LOADER_DRIVER_OVERRIDE=zink \
  -e "PATH=$rootfs/usr/bin:/usr/local/bin:/usr/bin" -- vkcube --c 10
rm -rf -- "$runtime"
```

This is only an executable lookup choice. No library/ICD environment flags
or Mesa wrapper are needed at launch. For one-off opt-in use instead of
installing the default, `bin/with-mesa` remains available inside an x86 shell.

### Rollback the default

Run the exact command printed by activation, as the same user (or root):

```sh
python3 "$recipe/set-fex-default.py" rollback "$HOME/.fex-emu/mesa-default-backup.PRINTED_ID"
```

Rollback restores every changed config byte-for-byte, including the original
WinBox thunk selection, with ownership/mode retained. It first checks all
files and refuses to overwrite subsequent user edits. Backups and the Mesa
payload remain available. The helper has been tested on the live J704 by
rolling back, comparing both files to their originals, then enabling again.
Existing VMs need not be stopped; freshly started FEX processes use the current
selection. Do not remove the prefix until your applications using it exit.
After rolling back the default, the old payload-removal command is optional:

```sh
rm -rf -- /home/nugget/.local/share/fex-emu/RootFS/Ubuntu_24_04/opt/aurora-fex-mesa/df0e691a15
```

No apt reinstall, dpkg-divert reversal, host package rollback, service restart,
or reboot is needed. Rebuild/requalify the guest when the host Mesa source or
experimental GPU UAPI changes.

## Hardware validation

On 2026-11-05, with J704 `mesa-j704 1:26.3.0_devel.df0e691-1` and
`virglrenderer-aurora 1.3.0-1`, fresh VMs as `nugget` passed **unwrapped**
x86_64 Vulkan enumeration and a ten-frame cube, x86_64/i686 Zink GL 4.6
queries, an i686 ten-frame Vulkan cube, and x86_64 Wine `--version` and
`cmd /c ver` in a temporary prefix (Windows 10.0.19045).
GL reports `26.3.0-devel (git-df0e691a15)` / `AURORA_BOREALIS`; Vulkan reports
Apple M5 (G17G C0), Borealis, the same commit, and a single device. Loader
diagnostics confirm the `/opt` ICD of the correct ABI. Native plain `vkcube`
also passes; rootfs-first VM PATH selects x86 for the same plain command name.
Both ABIs also pass a direct one-device/commit query, EGL 1.5 initialization,
and GBM device creation. Process mappings confirm EGL, GBM, its backend,
Gallium, and Vulkan load from the matching `/opt` architecture directory.
The host kernel log had no new messages across all tests.
The old Ubuntu Vulkan tool prints `UNKNOWN_VkDriverId_value35`, but correctly
reports `driverName = Borealis` and the matching Mesa commit.

Kisak libraries/ICDs, dpkg state, and host packages are preserved. FEX and
WinBox configs are backed up; Wine prefixes and launchers are not edited.
This qualifies the smoke tests above, not all games or experimental M5 rendering.
