# 🖥️ Dedicated Server Hosting

Divine Client includes full support for deploying, managing, and connecting to self-hosted or remote Minecraft servers.

---

## 🚀 Server Architecture

The server package (`DivineServer.zip`) includes:
- **FastAPI / Python Web Backend**: Manages user accounts, cosmetics database, telemetry, and Discord OAuth2.
- **PaperMC Server Installer**: Automatic discovery and installation of the latest stable Paper 1.21.11 server builds.
- **Modrinth & Paper Plugin Search**: Integrated API to search, download, and update server-side Bukkit/Paper plugins with single-click installation.
- **Discord Bot**: Runs concurrently with the API server to handle verification codes and role management.

---

## 🛠️ Deploying the Server

1. Extract `DivineServer.zip` on your VPS or server machine:
   ```bash
   unzip DivineServer.zip -d /opt/divineserver
   cd /opt/divineserver
   ```
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure your environment variables in `.env`:
   ```env
   DISCORD_BOT_TOKEN=your_token_here
   DISCORD_CLIENT_ID=your_client_id_here
   DISCORD_CLIENT_SECRET=your_client_secret_here
   SECRET_KEY=your_secret_key_here
   PORT=8080
   ```
4. Start the server:
   ```bash
   python -m server.main
   ```
