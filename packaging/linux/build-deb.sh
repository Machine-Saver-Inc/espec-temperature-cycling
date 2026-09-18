#!/usr/bin/env bash
# Build espec-burn-in_<version>_amd64.deb from dist/EspecBurnIn.
set -euo pipefail

VERSION="${1:?usage: build-deb.sh <version>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAGE="$(mktemp -d)"
PKG="espec-burn-in_${VERSION}_amd64"

mkdir -p "$STAGE/$PKG/DEBIAN" \
         "$STAGE/$PKG/opt/espec-burn-in" \
         "$STAGE/$PKG/usr/share/applications" \
         "$STAGE/$PKG/usr/share/icons/hicolor/256x256/apps"

cp -r "$ROOT/dist/EspecBurnIn/." "$STAGE/$PKG/opt/espec-burn-in/"
cp "$ROOT/packaging/linux/espec-burn-in.desktop" "$STAGE/$PKG/usr/share/applications/"
cp "$ROOT/packaging/linux/espec-burn-in.png" \
   "$STAGE/$PKG/usr/share/icons/hicolor/256x256/apps/espec-burn-in.png"

cat > "$STAGE/$PKG/DEBIAN/control" <<CONTROL
Package: espec-burn-in
Version: ${VERSION}
Section: science
Priority: optional
Architecture: amd64
Maintainer: Machine Saver Inc <support@machinesaver.net>
Description: Temperature cycling for PCB burn-in
 Drives an Espec temperature chamber through a 48-hour thermal cycle via its
 Watlow F4 controller over Modbus RTU, logging the result.
CONTROL

# Do not silently change the user's groups; tell them instead.
cat > "$STAGE/$PKG/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
echo "Espec Burn-In installed."
echo "Serial ports need group membership. If the program cannot open the port, run:"
echo "    sudo usermod -aG dialout \$USER"
echo "then log out and back in."
POSTINST
chmod 0755 "$STAGE/$PKG/DEBIAN/postinst"

dpkg-deb --build --root-owner-group "$STAGE/$PKG" "$ROOT/dist/${PKG}.deb"
echo "built dist/${PKG}.deb"
