/**
 * Divine Client - REST API Client Wrapper
 */

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

window.openModal = function(modalId) {
  const el = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
  if (el) {
    el.classList.add('active');
    if (el.style.display === 'none') el.style.display = 'flex';
  }
};

window.closeModal = function(modalId) {
  const el = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
  if (el) {
    el.classList.remove('active');
  }
};

const API = {
  async getStatus() {
    const res = await fetch("/api/status");
    return res.json();
  },

  async getInstances() {
    const res = await fetch("/api/instances");
    return res.json();
  },

  async createInstance(payload) {
    const res = await fetch("/api/instances", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return res.json();
  },

  async updateInstance(instanceId, payload) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return res.json();
  },

  async deleteInstance(instanceId) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}`, {
      method: "DELETE",
    });
    return res.json();
  },

  async cloneInstance(instanceId) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/clone`, {
      method: "POST",
    });
    return res.json();
  },

  async openInstanceFolder(instanceId) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/open-folder`, {
      method: "POST",
    });
    return res.json();
  },

  async getInstanceMods(instanceId) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/mods`);
    return res.json();
  },

  async toggleMod(instanceId, filename, enable) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/mods/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, enable }),
    });
    return res.json();
  },

  async deleteMod(instanceId, filename) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/mods/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });
    return res.json();
  },

  async getInstanceWorlds(instanceId) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/worlds`);
    return res.json();
  },

  async deleteWorld(instanceId, name) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/worlds/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    return res.json();
  },

  async getInstanceResourcePacks(instanceId) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/resourcepacks`);
    return res.json();
  },

  async toggleResourcePack(instanceId, filename, enable) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/resourcepacks/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, enable }),
    });
    return res.json();
  },

  async deleteResourcePack(instanceId, filename) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/resourcepacks/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });
    return res.json();
  },

  async getInstanceShaders(instanceId) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/shaders`);
    return res.json();
  },

  async toggleShader(instanceId, filename, enable) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/shaders/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, enable }),
    });
    return res.json();
  },

  async deleteShader(instanceId, filename) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/shaders/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });
    return res.json();
  },

  async fixModsCompatibility(instanceId) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/mods/fix-compatibility`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_fix: true }),
    });
    return res.json();
  },

  async optimizeInstance(instanceId) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/optimize`, {
      method: "POST",
    });
    return res.json();
  },

  async openInstanceSubfolder(instanceId, subfolder) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/open-subfolder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subfolder }),
    });
    return res.json();
  },

  async getLaunchStatus() {
    const res = await fetch("/api/launch/status");
    return res.json();
  },

  async launchGame(instanceId) {
    const res = await fetch("/api/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instance_id: instanceId }),
    });
    return res.json();
  },

  async stopGame(instanceId) {
    const res = await fetch("/api/launch/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instance_id: instanceId }),
    });
    return res.json();
  },

  async killGame(instanceId) {
    const res = await fetch("/api/launch/kill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instance_id: instanceId }),
    });
    return res.json();
  },

  async getGameLogs(instanceId) {
    const res = await fetch(`/api/launch/logs?instance_id=${encodeURIComponent(instanceId || "")}`);
    return res.json();
  },

  async searchModrinth(query, category = "", loader = "", version = "", projectType = "mod", index = "downloads", limit = 30, offset = 0) {
    const params = new URLSearchParams({
      q: query || "",
      category: category || "",
      loader: loader || "",
      version: version || "",
      project_type: projectType || "mod",
      index: index || "downloads",
      limit: limit || 30,
      offset: offset || 0,
    });
    const res = await fetch(`/api/modrinth/search?${params.toString()}`);
    return res.json();
  },

  async searchModpacks(query = "", version = "", index = "downloads", limit = 30, offset = 0) {
    const params = new URLSearchParams({
      q: query || "",
      version: version || "",
      index: index || "downloads",
      limit: limit || 30,
      offset: offset || 0,
    });
    const res = await fetch(`/api/modrinth/modpacks/search?${params.toString()}`);
    return res.json();
  },

  async installModpack(projectId, versionId = null, name = null) {
    const res = await fetch("/api/modrinth/modpacks/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        version_id: versionId,
        name: name,
      }),
    });
    return res.json();
  },

  async startInstallModpack(projectId, versionId = null, name = null) {
    const res = await fetch("/api/modrinth/modpacks/install/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        version_id: versionId,
        name: name,
        async: true
      }),
    });
    return res.json();
  },

  async getModpackInstallProgress(jobId) {
    const res = await fetch(`/api/modrinth/modpacks/install/progress/${encodeURIComponent(jobId)}`);
    return res.json();
  },

  async installModrinth(projectId, instanceId, versionId = null, projectType = "mod") {
    const res = await fetch("/api/modrinth/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        instance_id: instanceId,
        version_id: versionId,
        project_type: projectType,
      }),
    });
    return res.json();
  },

  async validateAndFixMods(instanceId, autoFix = true) {
    const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/mods/validate-and-fix`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_fix: autoFix }),
    });
    return res.json();
  },

  // Dedicated Servers
  async verifyServerPassword(password, remember = false) {
    const res = await fetch("/api/servers/verify-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, remember }),
    });
    return res.json();
  },

  async lockServers() {
    const res = await fetch("/api/servers/lock", { method: "POST" });
    return res.json();
  },

  async setServerPassword(currentPassword, newPassword) {
    const res = await fetch("/api/servers/set-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    return res.json();
  },

  async getServerTemplates() {
    const res = await fetch("/api/servers/templates");
    return res.json();
  },

  async getServerSessions() {
    const res = await fetch("/api/servers/sessions");
    return res.json();
  },

  async getServerInstances() {
    const res = await fetch("/api/servers/instances");
    return res.json();
  },

  async getServerQuota() {
    const res = await fetch("/api/servers/quota");
    return res.json();
  },

  async createServerInstance(data) {
    const res = await fetch("/api/servers/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  async createServer(data) {
    return this.createServerInstance(data);
  },

  async importServerInstance(instanceId) {
    const res = await fetch("/api/servers/import-instance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instance_id: instanceId }),
    });
    return res.json();
  },

  async deleteServerInstance(instanceId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/delete`, {
      method: "POST",
    });
    return res.json();
  },

  async getServerInfo(instanceId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/info`);
    return res.json();
  },

  async getServerProperties(instanceId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/properties`);
    return res.json();
  },

  async saveServerProperties(instanceId, properties) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/properties`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ properties }),
    });
    return res.json();
  },

  async getServerPlugins(instanceId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/plugins`);
    return res.json();
  },

  async installServerPlugin(instanceId, pluginName, version = null) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/plugins/install`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: pluginName, version }),
    });
    return res.json();
  },

  async deleteServerPlugin(instanceId, filename) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/plugins/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });
    return res.json();
  },

  async searchServerPlugins(query, mcVersion = "1.21.1") {
    const params = new URLSearchParams({ q: query, version: mcVersion });
    const res = await fetch(`/api/plugins/search?${params.toString()}`);
    return res.json();
  },

  async getServerWhitelist(instanceId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/whitelist`);
    return res.json();
  },

  async saveServerWhitelist(instanceId, whitelist) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/whitelist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ whitelist }),
    });
    return res.json();
  },

  async getServerOps(instanceId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/ops`);
    return res.json();
  },

  async saveServerOps(instanceId, ops) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/ops`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ops }),
    });
    return res.json();
  },

  async getServerFiles(instanceId, subpath = "") {
    const params = new URLSearchParams({ path: subpath });
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/files?${params.toString()}`);
    return res.json();
  },

  async readServerFile(instanceId, filepath) {
    const params = new URLSearchParams({ path: filepath });
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/files/read?${params.toString()}`);
    return res.json();
  },

  async writeServerFile(instanceId, filepath, content) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/files/write`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: filepath, content }),
    });
    return res.json();
  },

  async deleteServerFile(instanceId, filepath) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/files/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: filepath }),
    });
    return res.json();
  },

  async getServerAccess(instanceId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/access`);
    return res.json();
  },

  async addServerSubUser(instanceId, username, permissions = []) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/access/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, permissions }),
    });
    return res.json();
  },

  async removeServerSubUser(instanceId, username) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/access/remove`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    return res.json();
  },

  async openServerWindow(instanceId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/open-window`, {
      method: "POST",
    });
    return res.json();
  },

  async openServerFolder(instanceId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(instanceId)}/open-folder`, {
      method: "POST",
    });
    return res.json();
  },

  async startServer(instanceId, ramMb = 2048, tunnelProvider = "bore") {
    const res = await fetch("/api/servers/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instance_id: instanceId,
        ram_mb: ramMb,
        tunnel_provider: tunnelProvider,
      }),
    });
    return res.json();
  },

  async stopServer(sessionId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(sessionId)}/stop`, {
      method: "POST",
    });
    return res.json();
  },

  async restartServer(sessionId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(sessionId)}/restart`, {
      method: "POST",
    });
    return res.json();
  },

  async killServer(sessionId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(sessionId)}/kill`, {
      method: "POST",
    });
    return res.json();
  },

  async sendServerCommand(sessionId, command) {
    const res = await fetch(`/api/servers/${encodeURIComponent(sessionId)}/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command }),
    });
    return res.json();
  },

  async getServerConsole(sessionId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(sessionId)}/console`);
    return res.json();
  },

  // Accounts
  async getAccounts() {
    const res = await fetch("/api/accounts");
    return res.json();
  },

  async setActiveAccount(accountId) {
    const res = await fetch("/api/accounts/active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accountId }),
    });
    return res.json();
  },

  async addOfflineAccount(username) {
    const res = await fetch("/api/accounts/offline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    return res.json();
  },

  async startMicrosoftLogin() {
    const res = await fetch("/api/accounts/microsoft/start", { method: "POST" });
    return res.json();
  },

  async pollMicrosoftLogin(deviceCode, interval, expiresIn) {
    const res = await fetch("/api/accounts/microsoft/poll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_code: deviceCode, interval, expires_in: expiresIn }),
    });
    return res.json();
  },

  async deleteAccount(accountId) {
    const res = await fetch(`/api/accounts/${encodeURIComponent(accountId)}`, {
      method: "DELETE",
    });
    return res.json();
  },

  // News & Social
  async getNews() {
    const res = await fetch("/api/news");
    return res.json();
  },

  async getFriends() {
    const res = await fetch("/api/social/friends");
    return res.json();
  },

  async addFriend(username) {
    const res = await fetch("/api/social/friends/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    return res.json();
  },

  async acceptFriend(userId) {
    const res = await fetch("/api/social/friends/accept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    return res.json();
  },

  async removeFriend(userId) {
    const res = await fetch("/api/social/friends/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    return res.json();
  },

  async getSocialLink() {
    const res = await fetch("/api/social/link");
    return res.json();
  },

  async fixJavaRuntime() {
    try {
      const res = await fetch("/api/system/fix-java", {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      return await res.json();
    } catch (e) {
      return { success: false, error: e.message };
    }
  },

  async getLaunchLogs(instanceId = "") {
    try {
      const res = await fetch(`/api/launch/logs?instance_id=${encodeURIComponent(instanceId)}`);
      return await res.json();
    } catch (e) {
      return { logs: [], status: "idle" };
    }
  },

  async detectLocalDiscord() {
    try {
      const res = await fetch("/api/social/discord/local-detect");
      return await res.json();
    } catch (e) {
      return { running: false };
    }
  },

  async autoLinkLocalDiscord() {
    try {
      const res = await fetch("/api/social/discord/auto-link", {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      return await res.json();
    } catch (e) {
      return { success: false };
    }
  },

  async startSocialLink() {
    const res = await fetch("/api/social/link/start", { method: "POST" });
    return res.json();
  },

  async pollSocialLink(linkId) {
    const res = await fetch("/api/social/link/poll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ link_id: linkId }),
    });
    return res.json();
  },

  async unlinkSocialLink() {
    const res = await fetch("/api/social/link/unlink", { method: "POST" });
    return res.json();
  },

  async syncDiscordFriends() {
    const res = await fetch("/api/social/discord-sync", { method: "POST" });
    return res.json();
  },

  async quickDiscordAuth(username = "Player", discordId = "") {
    const res = await fetch("/api/social/link/quick-auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, discord_id: discordId }),
    });
    return res.json();
  },

  // Settings & System
  async getSettings() {
    const res = await fetch("/api/settings");
    return res.json();
  },

  async saveSettings(settings) {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    return res.json();
  },

  async getJavaRuntimes() {
    const res = await fetch("/api/java/runtimes");
    return res.json();
  },

  async installJava(version) {
    const res = await fetch("/api/java/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    });
    return res.json();
  },

  async getMinecraftVersions() {
    const res = await fetch("/api/minecraft/versions");
    return res.json();
  },

  async getPaperVersions() {
    const res = await fetch("/api/servers/paper-versions");
    return res.json();
  },

  // Storage & Directory Locations
  async getStorageLocations() {
    const res = await fetch("/api/storage/locations");
    return res.json();
  },

  async setStorageLocations(gameDir, instancesDir = null, moveFiles = true) {
    const res = await fetch("/api/storage/locations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        game_dir: gameDir,
        instances_dir: instancesDir,
        move_files: moveFiles,
      }),
    });
    return res.json();
  },

  async openStorageFolder(targetPath = null) {
    const res = await fetch("/api/storage/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: targetPath }),
    });
    return res.json();
  },

  // In-Game Client Mod & Cosmetics API
  async getIngameMods() {
    const res = await fetch("/api/ingame/mods");
    return res.json();
  },

  async toggleIngameMod(modId, enabled = null) {
    const res = await fetch(`/api/ingame/mods/${modId}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(enabled !== null ? { enabled } : {}),
    });
    return res.json();
  },

  async updateIngameModOptions(modId, options) {
    const res = await fetch(`/api/ingame/mods/${modId}/options`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ options }),
    });
    return res.json();
  },

  async getCosmetics() {
    const res = await fetch("/api/ingame/cosmetics");
    return res.json();
  },

  async equipCosmetic(slot, itemId) {
    const res = await fetch("/api/ingame/cosmetics/equip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot, item_id: itemId }),
    });
    return res.json();
  },

  async redeemPromoCode(code) {
    const res = await fetch("/api/ingame/cosmetics/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    return res.json();
  },

  async lookupPlayerBadge(username) {
    const res = await fetch(`/api/ingame/badge-lookup?username=${encodeURIComponent(username)}`);
    return res.json();
  },

  async getIngameFriends() {
    const res = await fetch("/api/ingame/friends");
    return res.json();
  },

  // Aliases for compatibility
  getConfig() { return this.getSettings(); },
  updateConfig(cfg) { return this.saveSettings(cfg); },
  launchInstance(id) { return this.launchGame(id); },
  startMicrosoftAuth() { return this.startMicrosoftLogin(); },
  pollMicrosoftAuth(code) { return this.pollMicrosoftLogin(code, 3, 300); },
  redeemKey(code) { return this.redeemServerCode(code); },
};

window.API = API;
