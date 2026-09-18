## Download

| Your computer | File to download |
| --- | --- |
| **Windows 10 / 11** | `EspecBurnIn-Setup-<version>.exe` |
| **Debian / Ubuntu** | `espec-burn-in_<version>_amd64.deb` |
| **Other Linux** | `EspecBurnIn-<version>-x86_64.AppImage` |

All the files are in the **Assets** list at the bottom of this page, with their
exact sizes. Nothing else is needed — Python, Qt and every dependency are
bundled, so the downloads are large (40–90 MB) but there is nothing to install
afterwards.

### Installing on Windows

1. Download `EspecBurnIn-Setup-<version>.exe` from **Assets** below.
2. Double-click it.
3. Windows will say **"Windows protected your PC"**. That is expected — the
   installer is not code-signed yet. Click **More info**, then **Run anyway**.
4. Click through the installer. It needs **no administrator rights**. Leave
   *Create a desktop shortcut* ticked.
5. Launch **Espec Burn-In** from the desktop icon.

### Installing on Linux

```sh
# Debian / Ubuntu
sudo apt install ./espec-burn-in_<version>_amd64.deb

# Anything else
chmod +x EspecBurnIn-*.AppImage && ./EspecBurnIn-*.AppImage
```

If the program cannot open the serial port:

```sh
sudo usermod -aG dialout $USER   # then log out and back in
```

### First run

Open the program, choose **Start a burn-in run**, pick the port the chamber is
plugged into and press **Test connection**. A green *Chamber is at 23.6 °C* is
what confirms the right port — not the port name. If no ports are listed, or the
chamber does not answer, the program shows you what to check.

Full instructions: [README](https://github.com/Machine-Saver-Inc/espec-temperature-cycling#readme) ·
[Troubleshooting](https://github.com/Machine-Saver-Inc/espec-temperature-cycling/blob/main/docs/TROUBLESHOOTING.md)

---

> This program is not a safety system. The chamber's independent
> over-temperature limit controller is the protective device, and must be set
> correctly and working before any unattended run.

### Verifying your download

`SHA256SUMS` is attached below and is what the in-app updater checks against.

```sh
sha256sum -c SHA256SUMS --ignore-missing
```
