set -e

rm -rf dist
echo "[*] Compiling with Nukita..."
python3 -m nuitka \
  --standalone \
  --follow-imports \
  --include-package=modules \
  --include-package=protocol \
  --enable-plugin=multiprocessing \
  --enable-plugin=anti-bloat \
  --assume-yes-for-downloads \
  --output-dir=dist \
  catsniffer.py

echo "[+] Build finished"
