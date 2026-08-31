#!/usr/bin/env bash
# Build and validate at the final path, then atomically switch current.
set -euo pipefail

SRC_DIR="${1:?usage: install_release.sh <uploaded-source-dir>}"
VERSION="$(PYTHONPATH="${SRC_DIR}/src" python3 -c 'from deskcamdio import __version__; print(__version__)')"
ROOT="/opt/deskcamdio"
RELEASE_DIR="${ROOT}/releases/${VERSION}"
NEXT_LINK="${ROOT}/current.next"
CREATED=0

cleanup() {
    sudo rm -f -- "${NEXT_LINK}"
    if [[ "${CREATED}" == 1 ]]; then
        current_target="$(readlink -f "${ROOT}/current" 2>/dev/null || true)"
        if [[ "${current_target}" != "${RELEASE_DIR}" ]]; then
            sudo rm -rf -- "${RELEASE_DIR}"
        fi
    fi
}
trap cleanup ERR INT TERM

echo "==> 1/8 create immutable release ${VERSION}"
if [[ -e "${RELEASE_DIR}" ]]; then
    echo "FATAL: release already exists: ${RELEASE_DIR}" >&2
    exit 1
fi
sudo mkdir -p "${RELEASE_DIR}"
CREATED=1
sudo cp -a "${SRC_DIR}/." "${RELEASE_DIR}/"

echo "==> 2/8 create final-path venv"
sudo python3 -m venv --system-site-packages "${RELEASE_DIR}/venv"

echo "==> 3/8 install locked artifacts"
DESKCAMDIO_WHEEL=("${RELEASE_DIR}"/wheelhouse/deskcamdio-"${VERSION}"-*.whl)
[[ -f "${DESKCAMDIO_WHEEL[0]}" ]] || { echo "FATAL: DeskCamdio wheel missing" >&2; exit 1; }
PYGAME_WHEEL=("${RELEASE_DIR}"/wheelhouse/pygame_ce-2.5.8-*.whl)
[[ -f "${PYGAME_WHEEL[0]}" ]] || { echo "FATAL: pygame-ce ARM64 wheel missing" >&2; exit 1; }
sudo "${RELEASE_DIR}/venv/bin/pip" install --no-index --no-deps \
    "${PYGAME_WHEEL[0]}" "${DESKCAMDIO_WHEEL[0]}"
if [[ "${DESKCAMDIO_ASR_MODE:-local}" == "local" ]]; then
    sudo "${RELEASE_DIR}/venv/bin/pip" install --no-index --no-deps \
        "${RELEASE_DIR}"/wheelhouse/sherpa_onnx_core-1.13.6-*.whl \
        "${RELEASE_DIR}"/wheelhouse/sherpa_onnx-1.13.6-*.whl
fi

echo "==> 4/8 Python and hardware dependency checks"
"${RELEASE_DIR}/venv/bin/python" -c "import deskcamdio; assert deskcamdio.__version__ == '${VERSION}'"
"${RELEASE_DIR}/venv/bin/python" -c "import pygame, httpx, PIL, gpiozero, evdev; assert pygame.__version__ == '2.5.8'"
if [[ "${DESKCAMDIO_ASR_MODE:-local}" == "local" ]]; then
    "${RELEASE_DIR}/venv/bin/python" -c "import sherpa_onnx"
fi
head -1 "${RELEASE_DIR}/venv/bin/deskcamdio-device" | grep -q "#!${RELEASE_DIR}/venv/bin/python"

echo "==> 5/8 application selftest"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy DESKCAMDIO_HEADLESS=1 \
    "${RELEASE_DIR}/venv/bin/deskcamdio-device" --selftest | grep -q "selftest OK"

echo "==> 6/8 mGBA self-containment"
MGBA_DIR="${RELEASE_DIR}/deploy/native/aarch64/mgba"
[[ -f "${MGBA_DIR}/mgba" ]] || { echo "FATAL: bundled mGBA binary missing" >&2; exit 1; }
[[ -f "${MGBA_DIR}/libmgba.so.0.10" ]] || { echo "FATAL: bundled libmgba missing" >&2; exit 1; }
# Windows/ZIP/SCP staging can strip the executable bit even though the ELF
# payload is intact.  Restore it before validating instead of silently
# skipping the entire mGBA gate.
sudo chmod 0755 "${MGBA_DIR}/mgba"
"${MGBA_DIR}/mgba" --version >/dev/null

echo "==> 7/8 install service and data ownership"
sudo cp -f "${RELEASE_DIR}/deploy/systemd/deskcamdio.service" /etc/systemd/system/
sudo mkdir -p /var/lib/deskcamdio /run/deskcamdio
sudo chown -R fish:fish /var/lib/deskcamdio /run/deskcamdio
sudo systemctl daemon-reload

echo "==> 8/8 atomic current switch"
sudo ln -s "releases/${VERSION}" "${NEXT_LINK}"
sudo mv -Tf "${NEXT_LINK}" "${ROOT}/current"
CREATED=0
trap - ERR INT TERM
echo "Installed ${VERSION}. Start with: sudo systemctl enable --now deskcamdio.service"
