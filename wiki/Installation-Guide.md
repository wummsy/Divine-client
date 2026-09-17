# 🚀 Installation Guide

Getting started with Divine Client is fast and straightforward.

---

## 📋 System Requirements

| Component | Minimum | Recommended |
| :--- | :--- | :--- |
| **Operating System** | Windows 10/11 64-bit, macOS 11+, or Linux (Ubuntu 20.04+) | Windows 11 64-bit / Linux |
| **Processor** | Intel Core i3 / AMD Ryzen 3 (64-bit) | Intel Core i5 / AMD Ryzen 5 or better |
| **RAM** | 4 GB | 8 GB or 16 GB |
| **Disk Space** | 2 GB free disk space | 5 GB SSD storage |
| **Java Runtime** | Java 21 (Auto-installed if missing) | Eclipse Temurin OpenJDK 21 |

---

## 💻 Installation Methods

### 1. Standalone Installer (Windows & Cross-Platform)
1. Download `DivineInstaller.zip` from releases.
2. Extract the archive and execute `installer.py` or run `build_installer.bat`.
3. Select your target installation directory (defaults to `%APPDATA%\.divineclient` or `~/.divineclient`).
4. Click **Install**. The installer will download all required libraries, assets, and configure launch shortcuts.

### 2. Portable Launcher Package
1. Download `DivineClient-v4.0.0.zip`.
2. Extract the folder to any directory.
3. On Windows, double-click `start.bat`.
4. On Linux / macOS, open a terminal and run:
   ```bash
   chmod +x start.sh
   ./start.sh
   ```

---

## ☕ Java 21 Runtime Setup & Repair

Divine Client relies on Java 21 LTS for Minecraft 1.21.11 compatibility. The client automatically monitors your environment:

- If no compatible Java 21 is detected, clicking **Fix Java** in the launcher will automatically fetch, extract, and configure Adoptium Temurin 21.
- You can also manually configure your custom Java executable path under **Settings** > **Java Runtime Path**.
