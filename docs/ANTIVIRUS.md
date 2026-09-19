# Windows Defender & Antivirus Guidance

This document explains why antivirus or Windows SmartScreen may flag unsigned builds of Divine Client, and how to safely allow it without disabling your security protection.

---

## Why Does Windows Defender or SmartScreen Flag the Launcher?

Divine Client is an open-source Minecraft launcher. New builds or unsigned executables may trigger false positives in behaviour-based scanners (such as Windows Defender or SmartScreen) for the following reasons:
1. **Unsigned Executables**: Windows SmartScreen establishes reputation based on cryptographic signatures and download volume. A fresh, unsigned release will show "Windows protected your PC / Unknown Publisher".
2. **Runtime Management**: The launcher downloads Java (Adoptium Temurin OpenJDK), manages sandbox directories, and executes Minecraft processes, which heuristic scanners can flag if unrecognized.

> **Never disable your antivirus or real-time protection.** Instead, add narrow exclusions for Divine Client specifically.

---

## Safe Exclusions via Helper Script

We provide transparent scripts in `tools/` that add exclusions only for Divine Client's folders:

- **`tools/add_defender_exclusions.bat`**: Double-click to request elevation and configure exclusions.
- **`tools/defender_exclusions.ps1`**: The underlying PowerShell script. It excludes:
  - The application folder (where `DivineClient.exe` lives).
  - The data directory (`%APPDATA%\.divineclient` or custom data directory).
  - The process `DivineClient.exe`.

To remove the exclusions at any time:
```powershell
powershell -ExecutionPolicy Bypass -File tools/defender_exclusions.ps1 -Remove
```

---

## Manual Exclusion Steps in Windows Security

1. Open **Windows Security** > **Virus & threat protection**.
2. Under **Virus & threat protection settings**, click **Manage settings**.
3. Under **Exclusions**, click **Add or remove exclusions**.
4. Click **Add an exclusion** > **Folder** and select your Divine Client folder (e.g. `%APPDATA%\.divineclient`).

---

## Code Signing (For Maintainers & Builders)

To eliminate SmartScreen warnings on release builds, sign the binaries with a valid Authenticode Code Signing Certificate:

```cmd
build_exe.bat -sign
```

Or manually using `signtool.exe`:
```cmd
signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /a dist\DivineClient\DivineClient.exe
```
