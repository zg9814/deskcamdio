#!/usr/bin/env bash
# Native mGBA build for Raspberry Pi OS 64-bit (guide §11.1).
# Produces deploy/native/aarch64/mgba/mgba + records version/SHA-256.
set -euo pipefail

MGBA_REPO="${MGBA_REPO:-https://github.com/mgba-emu/mgba.git}"
MGBA_REF="${MGBA_REF:-0.10.5}"          # fixed upstream tag; override to pin a SHA
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${PROJECT_ROOT}/deploy/native/aarch64/mgba"
BUILD_DIR="${TMPDIR:-/tmp}/mgba-build-$$"
JOBS="${JOBS:-2}"

echo "==> Preparing temporary swap (Zero 2 W has little RAM)"
if ! swapon --show=NAME,SIZE | grep -q '/swapfile-extra'; then
    sudo fallocate -l 1G /swapfile-extra || true
    sudo chmod 600 /swapfile-extra || true
    sudo mkswap /swapfile-extra >/dev/null || true
    sudo swapon /swapfile-extra || true
fi

echo "==> Installing build dependencies (apt, once)"
sudo apt-get update -qq
sudo apt-get install -y -qq git cmake ninja-build build-essential \
    libelf-dev libpng-dev libsdl2-dev zlib1g-dev libzip-dev libsqlite3-dev \
    libedit-dev libavcodec-dev libavutil-dev libswresample-dev 2>/dev/null || true

echo "==> Cloning mgba ${MGBA_REF}"
rm -rf "${BUILD_DIR}"
git clone --depth 1 --branch "${MGBA_REF}" "${MGBA_REPO}" "${BUILD_DIR}"
cd "${BUILD_DIR}"
ACTUAL_SHA="$(git rev-parse HEAD)"

echo "==> Configuring (GBA core + SDL only)"
cmake -S . -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_QT=OFF \
    -DBUILD_SDL=ON \
    -DBUILD_GBA=ON \
    -DBUILD_GB=OFF \
    -DBUILD_LIBRETRO=OFF \
    -DBUILD_TEST=OFF \
    -DUSE_FFMPEG=OFF \
    -DUSE_LUA=OFF \
    -DUSE_DEBUGGERS=OFF \
    -DUSE_ELF=ON \
    -DUSE_MINIZIP=OFF \
    -DUSE_PNG=ON \
    -DUSE_ZLIB=ON

echo "==> Building (-j${JOBS})"
cmake --build build --parallel "${JOBS}"

echo "==> Strip + collect artifacts"
strip build/sdl/mgba
mkdir -p "${OUT_DIR}"

# mGBA's SDL frontend links libmgba.so.0.10 dynamically; ship the shared lib
# next to the binary and point rpath at $ORIGIN so the release is self-contained
# (a binary-only deploy fails at runtime with "libmgba.so.0.10: not found").
LIBMGBA="$(find build -maxdepth 2 -name 'libmgba.so*' -type f | head -1)"
if [[ -z "${LIBMGBA}" ]]; then
    echo "!! libmgba shared library not built -- aborting" >&2
    exit 1
fi
cp build/sdl/mgba "${OUT_DIR}/mgba"
cp "${LIBMGBA}" "${OUT_DIR}/libmgba.so.0.10"
ln -sf libmgba.so.0.10 "${OUT_DIR}/libmgba.so.0"
ln -sf libmgba.so.0.10 "${OUT_DIR}/libmgba.so"
patchelf --set-rpath '$ORIGIN' "${OUT_DIR}/mgba"
SHA256="$(sha256sum "${OUT_DIR}/mgba" | awk '{print $1}')"

cat > "${OUT_DIR}/BUILD_INFO.txt" <<EOF
mGBA ref:        ${MGBA_REF}
commit sha:      ${ACTUAL_SHA}
build host:      $(uname -m) / $(. /etc/os-release && echo "$PRETTY_NAME")
cmake flags:     BUILD_QT=OFF BUILD_SDL=ON BUILD_GBA=ON BUILD_GB=OFF
                 BUILD_LIBRETRO=OFF BUILD_TEST=OFF USE_FFMPEG=OFF USE_LUA=OFF
                 USE_DEBUGGERS=OFF
binary sha256:   ${SHA256}
lib sha256:      $(sha256sum "${OUT_DIR}/libmgba.so.0.10" | awk '{print $1}')
built at:        $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

echo "==> Disabling temp swap"
sudo swapoff /swapfile-extra 2>/dev/null || true

echo "Done: ${OUT_DIR}/mgba"
cat "${OUT_DIR}/BUILD_INFO.txt"
