<div align="center">
  <img src="arenclient/web/assets/emblem.png" width="96" height="96" alt="Divine Client Logo">
  <h1>Divine Client</h1>
  <p>A fast, lightweight Minecraft client and launcher built for Fabric 1.21.11 with built-in QoL mods, custom title screen, builder tools, and dedicated server hosting.</p>
</div>

---

## Highlights

- **Custom Flat Title Screen** &mdash; Replaces the vanilla main menu with a clean Lunar-style 2D menu (`Singleplayer`, `Multiplayer`, `Builder Tools`, `Cosmetics`, `Divine Mods`, `Options`, `Quit`).
- **In-Game Mod Suite** &mdash; Access the in-game mod overlay with `Right Shift` or `M`. Includes FPS, Coordinates + Nether calc, Keystrokes, Fullbright, Zoom, Armor Status, and Potion Timers.
- **Builder Preset (1.21.11)** &mdash; Pre-configured instance with Axiom, WorldEdit, Flashback (replay camera), and Fabric API out of the box.
- **Fast Game Launcher** &mdash; Caches versions locally to boot in under 2 seconds. Includes a live console viewer and an automatic Java 21 / missing DLL repair tool.
- **Discord Bot & Account Sync** &mdash; Links your Discord profile to sync cloaks and friends between the launcher and in-game. Moderation tools include hardware ban tracking via `DEV-XXXX` IDs.

---

## Default Controls & Keybindings

| Key | Action |
| :--- | :--- |
| `Right Shift` or `M` | Open in-game Divine Mod Menu & Settings |
| `C` | Smooth Cinematic Zoom |
| `G` | Toggle Fullbright / Gamma Boost |
| `B` | Toggle Builder HUD & Grid Snap (when Axiom is loaded) |
| `W`, `A`, `S`, `D` + `LMB`, `RMB` | Interactive Keystrokes HUD overlay |

---

## Getting Started

### Running the Launcher from Source

Requirements: Python 3.10+ and Java 21 (Adoptium Temurin recommended).

```bash
# Clone the repository
git clone https://github.com/wummsy/Divine-client.git
cd Divine-client

# Install Python dependencies
pip install -r requirements.txt

# Start the launcher
python main.py
```

### Building the Standalone Executable (Windows)

```bat
# Builds dist/DivineClient/DivineClient.exe
build_exe.bat
```

---

## Running the Web Backend & Discord Bot

The website and Discord bot run from the `server/` folder and share a SQLite database (`data/divine.db`).

```bash
cd server
pip install -r requirements.txt

# Copy example configuration and add your Discord bot credentials
cp .env.example .env

# Run both the web portal and bot in development
bash run_all.sh
```

Production service templates for systemd and reverse proxies are provided in `server/deploy/` (`divine-web.service`, `divine-bot.service`, `nginx-divineclient.conf`, and `Caddyfile`).

---

## Project Structure

```
Divine-client/
├── arenclient/             # Launcher core logic, web UI backend, and desktop frames
│   ├── core/               # Launch orchestration, Java resolver, Discord RPC
│   ├── ui/                 # Native window frames and dialogs
│   └── web/                # HTML5, CSS, and JS launcher dashboard
├── mod/                    # Fabric 1.21.11 in-game client mod (Java source & Mixins)
│   └── src/com/divine/     # TitleScreen, HUD renderer, and IPC bridge
├── assets/                 # Icons, backgrounds, and pre-packaged mod dependencies
├── server/                 # Flask OAuth2 portal, API routes, and Discord bot
├── tests/                  # Unit and integration test suites
├── installer.py            # Self-contained portable installer script
└── main.py                 # Desktop application entry point
```

---

## License

Copyright &copy; 2026 **wummsy / Divine Development Team**. All rights reserved.

This source code is proprietary. Unauthorized reproduction, modification, decompilation, redistribution, or rebranding is strictly prohibited. See [`LICENSE`](LICENSE) for terms.
