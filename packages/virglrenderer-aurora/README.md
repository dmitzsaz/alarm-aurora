# Aurora DRM native contexts

Aurora Linux reports DRM name `aurora` and version `1.0.0`, while retaining
`asahi_drm.h`, its ioctl numbers, and the Asahi virtio command protocol.
Virglrenderer 1.3.0 recognizes only `asahi`. With libkrun 1.19.7, the failed
DRM initialization also triggers a fallback without the configured cross-domain
channels. MUVM's X11 bridge then accepts clients but cannot reach host Xwayland;
applications remain alive without opening a window.

This package adds `aurora` as an alias of the existing Asahi backend. Both
device discovery and the later context open accept it, as does initialization
with a caller-supplied DRM fd. The native-context ID stays 4; DRM versions and
ccmds pass through unchanged. Keeping a single backend entry avoids selecting
the wrong name when contexts are reopened by context type.

The kernel identity comes from upstream commit
[`a97f7b8be0e`](https://github.com/aurora-silicon/linux/commit/a97f7b8be0ebf1c712a72b695abaaaa7f0dc1181).
The upstream Mesa companion change already accepts both names. No kernel
rollback or Mesa header replacement is needed for this dispatcher fix.

## Build and install

On **aarch64 Arch Linux**, as an ordinary user, from this directory:

```sh
makepkg --syncdeps --cleanbuild
sudo pacman -U ./virglrenderer-aurora-1.3.0-1-aarch64.pkg.tar.zst
```

These are instructions for the operator; this task did not install dependencies
or packages. The recipe preserves Arch 1.3.0-2's rendering features and replaces
the `virglrenderer` package. Existing libkrun consumers continue to use the same
library SONAME. A running MUVM keeps its already loaded library, so acceptance
requires a fresh VM. A normal MUVM invocation can join the existing server even
after installing the package.

For an isolated X11 test from the desktop terminal, keeping another VM alive:

```sh
probe_runtime=$(mktemp -d /run/user/1000/muvm-gpu.XXXXXX) || exit
XDG_RUNTIME_DIR="$probe_runtime" \
  PULSE_SERVER=unix:/run/user/1000/pulse/native \
  RUST_LOG=debug VIRGL_LOG_LEVEL=debug \
  ASAHI_M5_BRINGUP=1 MESA_LOADER_DRIVER_OVERRIDE=zink \
  muvm -- /usr/bin/vkcube --wsi xcb --c 10
rm -rf -- "$probe_runtime"
```

`DISPLAY` and `XAUTHORITY`, if set, must come from the desktop session. Expect
ten rendered frames, with no DRM initialization fallback, cross-domain error,
or rejected GPU submissions. Check the log as well as the exit status: an old
guest Mesa can return success after its GPU submissions have failed.

## Validation and guest Mesa

`check-backend-names.sh SOURCE` compiles the actual dispatcher with a fake DRM
device. It covers both names, supplied fds, device reopening, unrelated drivers,
and failure paths. It needs only a C compiler and runs on macOS too. `check()`
also runs the normal upstream Meson tests on the Arch build machine.

On J704, an anonymous in-memory copy of the installed library with its backend
name changed to `aurora` restored native guest GLX, X11 EGL, and a ten-frame
Vulkan cube on Borealis. This isolated the cause without replacing any system
library or stopping the user's VM. The source alias implementation passed the
dispatcher regression test; the full Arch package was not built or installed
during the read-only hardware investigation.

The tested FEX Ubuntu rootfs contains Kisak Mesa `26.1.6`, whereas the host uses
J704 Mesa `26.3.0-devel` (`df0e691a15`). Its x86 GLX query succeeds after the
transport fix, but its x86 Vulkan render probe gets rejected submissions and a
lost device. That guest is **not** a qualified rendering stack.

Aurora's existing `mesa-aurora-fex-guest` package builds x86_64/i686 Mesa in
lockstep with its host Mesa and layers it over the distro's FEX base. Follow
that model when moving the whole stack to Aurora packages. It is not a drop-in
upgrade for this user's Ubuntu directory rootfs or `mesa-j704` package. For that
rootfs, build the matching J704 Mesa sources for its x86 Ubuntu ABI and use a
separate rootfs/overlay for validation; keep its libc and dependent libraries
consistent. Copying the aarch64 host driver, or an Arch x86 library alone, into
the Ubuntu rootfs does not provide a compatible guest stack. This host package
does not change any FEX rootfs.
