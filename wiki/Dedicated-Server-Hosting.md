# 🖥️ Dedicated Server Hosting

Divine Client includes full support for deploying, managing, and connecting to self-hosted or remote Minecraft servers with built-in team collaboration and Discord permissions.

---

## 🚀 Server Architecture

The server package (`DivineServer.zip`) includes:
- **Python / Flask Web Backend**: Manages user accounts, player telemetry, server registration, and Discord OAuth2.
- **PaperMC Server Installer**: Automatic discovery and installation of the latest stable Paper server builds.
- **Modrinth & Paper Plugin Search**: Integrated API to search, download, and update server-side Bukkit/Paper plugins with single-click installation.
- **Discord Bot**: Runs concurrently with the API server to handle verification codes, role management, and server administration slash commands.
- **Granular Collaborator Access System**: Allows server owners to grant and revoke sub-user access to friends or team members by Discord username or ID.

---

## 👥 Collaborator & Team Access Management

Server owners can grant granular management permissions to friends or team members directly from the client interface or via Discord bot commands:

### Permission Tiers
- **Power Actions (`power`)**: Start, stop, restart, and force kill the Minecraft server instance.
- **Live Terminal Console (`console`)**: View live log streams and execute Minecraft server commands directly.
- **File Manager (`files`)**: Browse, edit, upload, download, and delete configuration files and world directories.
- **Player Control (`players`)**: Manage whitelist, ban/unban players, kick players, and configure OP operators.
- **Server Settings (`settings`)**: Modify server properties, adjust allocated RAM memory, and manage Bukkit/Paper plugins.
- **Network Config (`network`)**: Manage Bore tunnel configurations, public join addresses, and port allocations.

### Granting Access
1. Open the **Dedicated Servers** tab in Divine Client.
2. Click **Access** on the desired server card (or open the **Collaborators & Sub-Users** tab inside the server web panel).
3. Enter the collaborator's **Discord Username**, **User ID**, or **Divine Name**.
4. Select the desired permissions and click **Grant Access**.
5. Collaborators will automatically have the server appear in their **Shared Servers** list and will be whitelisted automatically.

---

## 🤖 Discord Slash Commands

Manage your dedicated servers and collaborator access directly from Discord:

| Slash Command | Parameters | Description |
|---|---|---|
| `/grantaccess` | `server_code`, `target`, `permissions` | Grant server management permissions to a Discord user. |
| `/revokeaccess` | `server_code`, `target` | Revoke collaborator access from a user. |
| `/serveraccess` | `server_code` | View all active collaborators and their permission badges. |
| `/sharedservers` | *None* | List all dedicated servers shared with you. |
| `/serverlist` | `target` (optional) | List active dedicated servers across the network or for a specific user. |
| `/clearserver` | `target` (optional) | Clear registered server records and invite codes. |

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
   python app.py
   ```
