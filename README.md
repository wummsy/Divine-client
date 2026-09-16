# 🌌 Divine Client (v4.0.0)

<p align="center">
  <img src="arenclient/web/assets/emblem.png" width="120" height="120" alt="Divine Client Emblem">
</p>

<p align="center">
  <b>High-Performance Minecraft Client Launcher • Fabric 1.21.11 Mod Suite • Dedicated Server Engine • Discord Integration</b>
</p>

<p align="center">
  <a href="https://divineclient.wispbyte.org"><img src="https://img.shields.io/badge/Website-divineclient.wispbyte.org-38bdf8?style=for-the-badge" alt="Website"></a>
  <a href="https://discord.gg/ER2haQtach"><img src="https://img.shields.io/badge/Discord-Join%20Community-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <img src="https://img.shields.io/badge/License-Proprietary-red?style=for-the-badge" alt="License">
</p>

---

## ✨ Features Overview

### 🎮 In-Game Client Mod (`DivineClientMod-1.0.0.jar`)
- **Lunar-Style Flat 2D Title Screen**: Sleek obsidian aesthetic with smooth buttons (`SINGLEPLAYER`, `MULTIPLAYER`, `BUILDER`, `COSMETICS`, `DIVINE MODS`, `OPTIONS`, `QUIT`).
- **Comprehensive In-Game QoL Suite (`Right Shift` / `M`)**:
  - FPS Display & Dynamic Coordinates (XYZ + Nether conversion).
  - Smooth Zoom (`C` key) & Gamma/Fullbright toggle (`G` key).
  - Sprint Toggle & KeyStrokes HUD with real-time mouse/keyboard press animations.
  - Armor & Potion Status HUD with remaining duration counters.
  - Hypixel Quickplay, Particle Changer, and UHC Overlay.
- **Divine User Nametag Badge**: Celestial white sun emblem rendered next to verified Divine players.
- **Builder Studio Tools**: Out-of-the-box support and packaging for Axiom, WorldEdit, and Flashback cinematic camera tools.

### 🚀 Desktop Launcher Architecture
- **Dual Main Menu Modes**:
  - **Divine Mode**: Dedicated celestial obsidian dashboard locked to Divine Client (1.21.11).
  - **Instances Mode**: Carousel slider showcasing custom instances and modpacks.
- **Sub-Second Fast Launching**: Intelligent disk caching skips redundant network crawlers when versions are already installed.
- **Live Game Output Console**: Real-time log streaming with auto-scroll, color coding, and copy/clear tools.
- **Automated Java Health & DLL Repair**: 1-click OpenJDK 21 LTS auto-repair that eliminates missing `jli.dll` and `jvm.dll` system errors.
- **Custom Game Directories**: Seamless directory configuration across storage drives with automated file migration.

### 🌐 Discord Gateway & Bot Integration
- **OAuth2 & 1-Click Verification**: Fast account linking via the web portal (`/link?code=XXXX`).
- **Discord Desktop Auto-Detection**: Probes local Discord client ports (`6463–6472`) for 1-click pairing.
- **DivineBot (`server/bot.py`)**:
  - `/link code:XXXX` - Link account directly inside Discord chat.
  - `/friends` & `/syncfriends` - Real-time synchronization between Discord mutuals and in-game friend lists.
  - `/lookup` & `/profile` - Player verification, hardware code audit, and cosmetic tracking.
  - `/ban` & `/unban` - Hardware device code (`DEV-XXXX-...`) moderation engine.
  - `/serverlist` & `/clearserver` - Dedicated server fleet manager.

---

## 📦 Repository Structure

```
.
├── arenclient/           # Launcher Core Engine & Web UI Frontend
│   ├── core/             # Launch flow, Java runtime, accounts, mods, Discord RPC
│   ├── ui/               # Desktop UI windows, dialogs, and themes
│   └── web/              # Glassmorphic HTML/CSS/JS frontend dashboard
├── assets/               # High-res icons, logos, animated GIFs, and bundled mod JARs
├── server/               # Flask Web Server, DivineBot, SQLite database, & deploy configs
│   ├── deploy/           # Systemd service units, Nginx, and Caddy configs
│   ├── templates/        # Starfield canvas website templates & /link gateway
│   ├── app.py            # Main web backend & OAuth2 router
│   └── bot.py            # DivineBot Discord integration bot
├── tests/                # Unittest test suites (100% passing)
├── main.py               # Launcher desktop entry point
├── installer.py          # Standalone client installer script
└── LICENSE               # Proprietary Source Code License (All Rights Reserved)
```

---

## 🔒 License & Copyright

Copyright © 2026 **wummsy / Divine Development Team**. All rights reserved.  
Unauthorized copying, modification, distribution, rebranding, or commercial use of this codebase is strictly prohibited. See [`LICENSE`](LICENSE) for full details.
