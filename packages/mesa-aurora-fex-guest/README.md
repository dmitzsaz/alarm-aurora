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

### Make it the default while preserving host thunks

If an earlier `set-fex-default.py` activation exported `/opt` graphics paths
and disabled GL/Vulkan thunks, **roll that activation back first** with its
printed backup command. The selector refuses that old environment so the
two activation methods cannot be mixed.

Run activation **as the FEX user inside MUVM**, so the rootfs's x86
`ldconfig.real` runs through FEX/binfmt. Use a fresh private runtime as in the
launch example below, and run this native Python command inside that VM:

```sh
/usr/bin/python3 "$recipe/set-fex-default.py" enable \
  "$HOME/.fex-emu/Config.json" "$rootfs" "$prefix"
```

Use the active FEX configuration directory, which may be legacy `~/.fex-emu`.
Activation verifies the rootfs and both payload ABIs, then:

- Adds `etc/ld.so.conf.d/00-aurora-fex-mesa.conf` **inside the guest rootfs**,
  with the prefix's two multiarch library directories before packaged paths.
- Generates an x86 multiarch `etc/ld.so.cache` using the guest's own
  `ldconfig.real`, `-X` (no symlink writes), and a temporary `-C` cache
  (no auxiliary-cache writes). It verifies the required libraries before
  replacing any files.
- Adds missing global FEX `Env` defaults: `VK_LOADER_DRIVERS_SELECT=asahi*`,
  `MESA_LOADER_DRIVER_OVERRIDE=zink`, and `ASAHI_M5_BRINGUP=1`. Existing
  values win. No x86 library, DRI, GBM, EGL or exclusive Vulkan paths are
  exported. The loader's simple glob syntax requires the suffix wildcard
  `asahi*`; do not use an embedded wildcard such as `asahi_icd*.json`.

Ubuntu's existing `asahi_icd.json` references the soname
`libvulkan_asahi.so`; each ABI resolves it through its own cache entries.
Its existing EGL vendor manifest similarly resolves `libEGL_mesa.so.0`.
Mesa's compiled prefix supplies the DRI/GBM search paths. The architecture
neutral Vulkan filename filter selects Ubuntu's `asahi_icd.json` and the
host's `asahi_icd.aarch64.json`, excluding unrelated/software ICDs. Thus the
guest sees one Apple M5 without imposing guest paths on a native loader.

**All ThunksDB settings, AppConfig files, AppOverrides, HostEnv,
FEX_APP_CONFIG files, launchers and Wine prefixes are preserved.** Thunked
programs keep using native host Mesa; non-thunked programs use guest Mesa.
Global or per-app graphics thunks are a user's choice. An app with its own
Env list may replace global Env defaults; retain the neutral defaults there
if desired. Explicit launcher loader variables still take precedence over
the cache. No activation should override deliberate per-app choices.

FEX stores string lists as repeated `"Env": "KEY=value"` keys. The helper
preserves object pairs, including repeated HostEnv, and never rewrites
AppConfig. Only the global config, new guest ld configuration and guest
loader cache enter its transactional backup. Repeating activation is a
no-op when the selection is already present. Keep the helper for rollback.

APT's ordinary guest ldconfig trigger includes the new first-priority conf,
so future package upgrades retain the prefix. No package-owned library,
manifest, diversion, package hook, host loader cache or host package is
changed. Requalify after guest/host upgrades; keep the selected payload.

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
Non-thunked Wine/WinBox launches resolve guest Mesa through the rootfs cache;
thunked launches retain native Mesa. Never export these x86 library/ICD paths
on the outer ARM MUVM process: libkrun's renderer uses native ARM libraries.

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

Rollback checks **every** activated hash before changing any file, refuses
later user edits (including a cache rebuilt by APT), restores original bytes,
mode, ownership and mtime, and removes a conf file that was originally absent.
It retains the payload and backups. It also understands the old config-only
backup format. When an APT update has rebuilt the cache, inspect the backup
and remove the managed guest conf/rebuild the guest cache deliberately rather
than overwriting the newer cache. No thunk or app file belongs to the new
activation, so rollback cannot overwrite later app/thunk choices.

After rolling back the default, the old payload-removal command is optional:

```sh
rm -rf -- /home/nugget/.local/share/fex-emu/RootFS/Ubuntu_24_04/opt/aurora-fex-mesa/df0e691a15
```

No apt reinstall, dpkg-divert reversal, host package rollback, service restart,
or reboot is needed. Rebuild/requalify the guest when the host Mesa source or
experimental GPU UAPI changes.

## Hardware validation

Guest GL/Vulkan/EGL/GBM smoke tests passed for both x86 ABIs on J704 with
matching Mesa `df0e691a15`. These results cover those smoke tests; full
Proton/DXVK application qualification remains pending.

The selector's host tests check preservation of thunk and per-app settings,
rollback, repeated activation, cache-generation failure and malformed payload
rejection. They mock the guest loader cache and do not establish rendering
correctness. After activation, verify both guest ABIs and any applications
that use native graphics thunks with the installed host and guest Mesa.
