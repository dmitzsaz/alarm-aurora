#!/bin/bash
# Run inside an Ubuntu 24.04 build chroot, not inside the live FEX rootfs.
set -euo pipefail
if (( $# != 5 )); then
  echo "Usage: $0 SOURCE BUILD DESTDIR PREFIX COMMIT" >&2
  exit 2
fi
source_dir=$(realpath "$1")
build_dir=$(realpath -m "$2")
stage_dir=$(realpath -m "$3")
prefix=$4
commit=$5
[[ $prefix =~ ^/opt/aurora-fex-mesa/[a-zA-Z0-9._-]+$ ]] || { echo 'Invalid prefix' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
jobs=${MESA_FEX_JOBS:-2}
export MESA_GIT_SHA1_OVERRIDE=$commit
unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS PKG_CONFIG_PATH PKG_CONFIG_LIBDIR
mkdir -p "$build_dir" "$stage_dir"
common=(--buildtype=release -Db_ndebug=true --wrap-mode=nodownload
  -Dbuild-tests=false -Dvalgrind=disabled -Dvideo-codecs=
  -Dmicrosoft-clc=disabled -Dgallium-rusticl=false -Dlibunwind=disabled
  -Dlmsensors=disabled)
# Build all executable shader generators natively from the SAME source.
# Neither target runtime links LLVM or needs Rust.
meson setup "$build_dir/tools" "$source_dir" "${common[@]}" \
  -Dplatforms= -Dgallium-drivers= -Dvulkan-drivers= -Dtools=asahi \
  -Dglx=disabled -Degl=disabled -Dgbm=disabled -Dllvm=enabled \
  -Dmesa-clc=enabled -Dprecomp-compiler=enabled
ninja -C "$build_dir/tools" -j"$jobs" \
  src/compiler/clc/mesa_clc src/compiler/spirv/vtn_bindgen2 src/asahi/clc/asahi_clc
cat > "$build_dir/tools.ini" <<TOOLS
[binaries]
mesa_clc = '$build_dir/tools/src/compiler/clc/mesa_clc'
vtn_bindgen2 = '$build_dir/tools/src/compiler/spirv/vtn_bindgen2'
asahi_clc = '$build_dir/tools/src/asahi/clc/asahi_clc'
TOOLS
for arch in x86_64 i686; do
  triplet=$arch-linux-gnu
  multiarch=$triplet
  cpu_family=$arch
  [[ $arch != i686 ]] || { multiarch=i386-linux-gnu; cpu_family=x86; }
  cat > "$build_dir/$arch.cross" <<CROSS
[binaries]
c = '$triplet-gcc'
cpp = '$triplet-g++'
ar = '$triplet-ar'
strip = '$triplet-strip'
pkg-config = 'pkg-config'
[properties]
pkg_config_libdir = '/usr/lib/$multiarch/pkgconfig:/usr/share/pkgconfig'
needs_exe_wrapper = true
[host_machine]
system = 'linux'
cpu_family = '$cpu_family'
cpu = '$arch'
endian = 'little'
CROSS
  meson setup "$build_dir/$arch" "$source_dir" "${common[@]}" \
    --prefix="$prefix" --libdir="lib/$multiarch" \
    --cross-file "$build_dir/$arch.cross" --native-file "$build_dir/tools.ini" \
    -Dplatforms=x11,wayland -Dgallium-drivers=asahi,zink,softpipe -Dvulkan-drivers=asahi \
    -Dvulkan-manifest-per-architecture=true -Dvulkan-layers= -Dglx=dri -Degl=enabled -Dgbm=enabled -Dgles1=disabled \
    -Dgles2=enabled -Dglvnd=enabled -Dllvm=disabled -Dspirv-tools=disabled \
    -Dmesa-clc=system -Dprecomp-compiler=system
  ninja -C "$build_dir/$arch" -j"$jobs"
  DESTDIR="$stage_dir" meson install -C "$build_dir/$arch" --no-rebuild --strip
  test -s "$stage_dir$prefix/share/vulkan/icd.d/asahi_icd.$arch.json"
done
printf '%s\n' "$commit" > "$stage_dir$prefix/.aurora-mesa-commit"
install -d "$stage_dir$prefix/bin"
sed "s|@PREFIX@|$prefix|g" "$script_dir/with-mesa.in" > "$stage_dir$prefix/bin/with-mesa"
chmod 755 "$stage_dir$prefix/bin/with-mesa"
install -Dm644 "$source_dir/docs/license.rst" \
  "$stage_dir$prefix/share/licenses/mesa-aurora-fex-guest/license.rst"
