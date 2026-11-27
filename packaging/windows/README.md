# Windows portable build

Produces `DX-Band-<version>-windows-x64.zip`. End users unzip and run `DX Band.exe`. Model weights are not packaged.

## Requirements

- 64-bit Windows
- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

Build on a local disk when possible; network shares are slower and less reliable for PyInstaller.

## Build

From the repository root in PowerShell:

```powershell
.\scripts\build_windows_release.ps1
```

Outputs:

- `dist\DX Band\` — unpacked app folder
- `dist\DX-Band-<version>-windows-x64.zip`
- `out\DX-Band-<version>-windows-x64.zip` — copy of the zip for handoff

After unpacking a release zip, users open **Settings → Creation Resources** and click **Download Missing Resources** to install multimedia tools and creation models when missing.
