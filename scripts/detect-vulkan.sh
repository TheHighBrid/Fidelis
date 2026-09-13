#!/data/data/com.termux/files/usr/bin/bash
set -u

printf 'Architecture: %s\n' "$(uname -m)"
printf 'ABI: %s\n' "$(getprop ro.product.cpu.abi 2>/dev/null || true)"
printf 'SDK: %s\n' "$(getprop ro.build.version.sdk 2>/dev/null || true)"
printf 'KGSL: %s\n' "$([[ -e /dev/kgsl-3d0 ]] && printf visible || printf missing)"
printf 'Vulkan loader: '
readlink -f "${PREFIX:-/data/data/com.termux/files/usr}/lib/libvulkan.so" 2>/dev/null || printf 'missing\n'
find "${PREFIX:-/data/data/com.termux/files/usr}/share/vulkan/icd.d" -maxdepth 1 -type f -print 2>/dev/null | sort
if command -v vulkaninfo >/dev/null 2>&1; then
  vulkaninfo --summary 2>&1 | sed -n '1,80p'
fi

