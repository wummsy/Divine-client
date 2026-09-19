
window.openModal = function(modalId) {
  const el = typeof modalId === "string" ? document.getElementById(modalId) : modalId;
  if (el) {
    el.classList.add("active");
    if (el.style.display === "none") el.style.display = "flex";
  }
};

window.closeModal = function(modalId) {
  const el = typeof modalId === "string" ? document.getElementById(modalId) : modalId;
  if (el) {
    el.classList.remove("active");
  }
};

async function fetchAndRenderInstances() {
  try {
    const instRes = await API.getInstances();
    if (instRes && instRes.instances) {
      AppState.instances = instRes.instances;
      renderHomeSlider();
      populateEditorInstanceSelect();
    }
  } catch (e) {
    console.error("Error fetching instances:", e);
  }
}

async function loadLauncherData() {
  await initClientData();
}

async function launchSpecificInstance(instanceId) {
  if (!instanceId) return;
  AppState.activeInstanceId = instanceId;
  const idx = (AppState.instances || []).findIndex(i => i.id === instanceId);
  if (idx >= 0) {
    AppState.sliderIndex = idx;
    renderHomeSlider();
  }
  await handleHeroPlayButtonClick();
}

async function launchEditorCurrentInstance() {
  const iid = AppState.currentEditorInstanceId || AppState.activeInstanceId;
  if (!iid) {
    showToast("No instance selected to launch.", "error");
    return;
  }
  await launchSpecificInstance(iid);
}

window.renderHeroSlider = renderHomeSlider;
window.fetchAndRenderInstances = fetchAndRenderInstances;
window.loadLauncherData = loadLauncherData;
window.launchSpecificInstance = launchSpecificInstance;
window.launchEditorCurrentInstance = launchEditorCurrentInstance;

/**
 * Divine Client v5.0.0 - Next-Gen Minecraft Launcher Frontend
 * Clean White & Obsidian Theme • Modpack Store • Instance Slider • Dedicated Editor
 */

const AppState = {
  currentTab: "overview",
  discordLinked: false,
  discordProfile: {},
  discordAuthCode: "",
  discordVerificationUrl: "",
  instances: [],
  activeInstanceId: null,
  sliderIndex: 0,
  accounts: [],
  activeAccountId: null,
  friends: [],
  incomingRequests: [],
  outgoingRequests: [],
  sharedServers: [],
  news: [],
  status: {},
  servers: [],
  serverUnlocked: false,
  currentEditorInstanceId: null,
  currentEditorMods: [],
  currentEditorResourcePacks: [],
  currentEditorShaders: [],
  // Store Filters (Modpacks Only)
  storeFilters: {
    category: "all",
    loader: "all",
    version: "all",
    type: "modpack",
    sort: "downloads",
    source: "modrinth",
    query: ""
  },
  storeDebounceTimer: null,
  modDebounceTimer: null,
  rpDebounceTimer: null,
  shaderDebounceTimer: null,
  isGameRunning: false,
  currentViewModpackData: null,
};

// -----------------------------------------------------------------------------
// Initialization & Startup Splash Dismissal
// -----------------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", async () => {
  try {
    await initClientData();
  } catch (err) {
    console.error("Initialization error:", err);
  } finally {
    // Smoothly fade out the clean windowless white logo animation screen
    setTimeout(() => {
      const splash = document.getElementById("startup-gateway-screen");
      if (splash) {
        splash.classList.add("fade-out");
        setTimeout(() => {
          splash.style.display = "none";
        }, 500);
      }
    }, 1200);
  }

  // Periodic telemetry poll
  setInterval(pollSystemStatus, 3000);
});

async function initClientData() {
  const savedTheme = localStorage.getItem("divine_theme") || "divine";
  applyTheme(savedTheme, false);

  const [statusRes, instRes, accRes, newsRes, friendsRes, srvRes, linkRes] = await Promise.allSettled([
    API.getStatus(),
    API.getInstances(),
    API.getAccounts(),
    API.getNews(),
    API.getFriends(),
    API.getServerInstances(),
    API.getSocialLink(),
  ]);

  if (linkRes.status === "fulfilled" && linkRes.value) {
    AppState.discordLinked = !!linkRes.value.linked;
    AppState.discordProfile = linkRes.value.profile || {};
  } else {
    AppState.discordLinked = false;
    AppState.discordProfile = {};
  }

  if (statusRes.status === "fulfilled" && statusRes.value) {
    AppState.status = statusRes.value;
    AppState.serverUnlocked = statusRes.value.servers?.unlocked || false;
    if (statusRes.value.is_discord_linked !== undefined && !AppState.discordLinked) {
      AppState.discordLinked = !!statusRes.value.is_discord_linked;
    }
  }

  if (instRes.status === "fulfilled" && instRes.value) {
    AppState.instances = instRes.value.instances || [];
    const lastId = AppState.status.active_instance?.id || (AppState.instances.length > 0 ? AppState.instances[0].id : null);
    AppState.activeInstanceId = lastId;
    const idx = AppState.instances.findIndex(i => i.id === lastId);
    AppState.sliderIndex = idx >= 0 ? idx : 0;
  }

  if (accRes.status === "fulfilled" && accRes.value) {
    AppState.accounts = accRes.value.accounts || [];
    AppState.activeAccountId = accRes.value.active_id || (AppState.accounts.length > 0 ? AppState.accounts[0].id : null);
  }

  if (newsRes.status === "fulfilled" && newsRes.value) {
    AppState.news = newsRes.value.news || [];
  }

  if (friendsRes.status === "fulfilled" && friendsRes.value) {
    AppState.friends = friendsRes.value.friends || [];
    AppState.incomingRequests = friendsRes.value.incoming || [];
    AppState.outgoingRequests = friendsRes.value.outgoing || [];
  }

  if (srvRes.status === "fulfilled" && srvRes.value) {
    AppState.servers = srvRes.value.servers || [];
  }

  renderTopbar();
  renderHomeSlider();
  renderAnnouncements();
  renderQuickFriends();
  loadSettingsDefaults();
  initHeroWallpaper();
  updateNavigationLockState();

  // Enforce Discord Login on client startup
  if (!AppState.discordLinked) {
    switchTab("discord");
  } else {
    switchTab("overview");
  }
}

async function pollSystemStatus() {
  try {
    const data = await API.getStatus();
    if (data) {
      AppState.status = data;
      const launch = data.launch_state || {};
      const isRunning = launch.status === "running" || (data.running_games && data.running_games.length > 0);
      const isLaunching = launch.status === "launching";
      updatePlayButtonVisuals(isRunning, isLaunching);
    }
  } catch (e) {}
}

// -----------------------------------------------------------------------------
// Navigation & Discord Lock State
// -----------------------------------------------------------------------------
function updateNavigationLockState() {
  const isLinked = !!AppState.discordLinked;
  const navItems = document.querySelectorAll(".sidebar-nav-item");
  navItems.forEach(btn => {
    const tab = btn.getAttribute("data-tab");
    if (tab === "discord") {
      btn.style.opacity = "1";
      btn.title = isLinked ? "Discord Profile & Community" : "Discord Login (Required)";
    } else {
      if (!isLinked) {
        btn.style.opacity = "0.4";
        btn.title = "Discord login required to unlock";
      } else {
        btn.style.opacity = "1";
        btn.title = btn.getAttribute("data-tooltip") || "";
      }
    }
  });

  const topbarLabel = document.getElementById("topbar-discord-label");
  if (topbarLabel) {
    topbarLabel.textContent = isLinked ? (AppState.discordProfile?.username ? `Discord: ${AppState.discordProfile.username}` : "Discord") : "Login Required";
    topbarLabel.style.color = isLinked ? "#ffffff" : "#ef4444";
  }
}

// -----------------------------------------------------------------------------
// Tab Switching
// -----------------------------------------------------------------------------
function switchTab(tabName) {
  // If user is not linked to Discord, force Discord login tab
  if (!AppState.discordLinked && tabName !== "discord") {
    showToast("Please sign in with Discord to access Divine Client.", "error");
    tabName = "discord";
  }

  AppState.currentTab = tabName;
  window.soundEngine?.playClick?.();

  document.querySelectorAll(".sidebar-nav-item").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-tab") === tabName);
  });

  document.querySelectorAll(".view-pane").forEach(pane => {
    pane.classList.toggle("active", pane.id === `view-${tabName}`);
  });

  const crumb = document.getElementById("topbar-crumb-active");
  const tabTitles = {
    overview: "HOME",
    modpacks: "MODPACK STORE",
    editor: "INSTANCE EDITOR",
    servers: "DEDICATED SERVERS",
    friends: "FRIENDS & NETWORK",
    discord: AppState.discordLinked ? "DISCORD ACCOUNT" : "DISCORD AUTHENTICATION REQUIRED"
  };
  if (crumb) crumb.textContent = tabTitles[tabName] || tabName.toUpperCase();

  if (tabName === "overview") {
    renderHomeSlider();
    renderAnnouncements();
    renderQuickFriends();
  } else if (tabName === "modpacks") {
    fetchStoreModpacks();
  } else if (tabName === "editor") {
    populateEditorInstanceSelect();
    loadInstanceIntoEditor(AppState.currentEditorInstanceId || AppState.activeInstanceId);
  } else if (tabName === "servers") {
    renderDedicatedServers();
    refreshDedicatedServers(true);
  } else if (tabName === "friends") {
    renderFriendsView();
    refreshDedicatedServers(true);
  } else if (tabName === "discord") {
    renderDiscordView();
  }
}

// -----------------------------------------------------------------------------
// Topbar & Account Profile Drawer
// -----------------------------------------------------------------------------
function renderTopbar() {
  const activeAcc = AppState.accounts.find(a => a.id === AppState.activeAccountId) || (AppState.accounts.length > 0 ? AppState.accounts[0] : null);
  const usernameEl = document.getElementById("topbar-username");
  const statusEl = document.getElementById("topbar-status-text");
  const topbarAvatar = document.getElementById("topbar-avatar-container");
  const drawerUsername = document.getElementById("drawer-username");
  const drawerType = document.getElementById("drawer-account-type");
  const drawerAvatar = document.getElementById("drawer-avatar-box");

  if (activeAcc) {
    const name = activeAcc.name || activeAcc.username || "Player";
    if (usernameEl) usernameEl.textContent = name;
    if (drawerUsername) drawerUsername.textContent = name;
    if (statusEl) statusEl.textContent = "ONLINE";
    if (drawerType) drawerType.textContent = activeAcc.type === "microsoft" ? "• Microsoft Account" : "• Offline Profile";

    const skinHead = `https://minotar.net/helm/${encodeURIComponent(name)}/36.png`;
    const avatarHtml = `<img src="${skinHead}" onerror="this.onerror=null;this.src='/assets/ui_account.png';" alt="${escapeHtml(name)}" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">`;
    if (topbarAvatar) topbarAvatar.innerHTML = avatarHtml;
    if (drawerAvatar) drawerAvatar.innerHTML = avatarHtml;
  } else {
    if (usernameEl) usernameEl.textContent = "Add Account";
    if (drawerUsername) drawerUsername.textContent = "No Account";
    if (statusEl) statusEl.textContent = "OFFLINE";
    if (drawerType) drawerType.textContent = "• No Active Profile";
    const defaultIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`;
    if (topbarAvatar) topbarAvatar.innerHTML = defaultIcon;
    if (drawerAvatar) drawerAvatar.innerHTML = defaultIcon;
  }

  renderSavedAccountsList();
}

function renderSavedAccountsList() {
  const listEl = document.getElementById("drawer-saved-accounts-list");
  if (!listEl) return;

  const accounts = AppState.accounts || [];
  if (accounts.length === 0) {
    listEl.innerHTML = `<div style="text-align:center;padding:12px;font-size:12px;color:#94a3b8;">No saved profiles. Click '+ Add Offline' above.</div>`;
    return;
  }

  listEl.innerHTML = "";
  accounts.forEach(acc => {
    const name = acc.name || acc.username || "Player";
    const isActive = acc.id === AppState.activeAccountId;
    const card = document.createElement("div");
    card.style.cssText = `display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:${isActive ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.04)'};border:1px solid ${isActive ? '#ffffff' : 'rgba(255,255,255,0.08)'};border-radius:8px;cursor:pointer;`;
    card.onclick = () => switchAccount(acc.id);

    card.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;">
        <img src="https://minotar.net/helm/${encodeURIComponent(name)}/32.png" onerror="this.onerror=null;this.src='/assets/ui_account.png';" style="width:28px;height:28px;border-radius:50%;">
        <div>
          <div style="font-size:13px;font-weight:800;color:#ffffff;">${escapeHtml(name)}</div>
          <div style="font-size:10.5px;color:#94a3b8;">${acc.type === 'microsoft' ? 'Microsoft' : 'Offline'}</div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        ${isActive ? '<span style="font-size:9.5px;font-weight:800;color:#22c55e;background:rgba(34,197,94,0.15);padding:2px 6px;border-radius:4px;">ACTIVE</span>' : ''}
        <button class="btn btn-secondary btn-sm" style="padding:2px 6px;color:#ef4444;" onclick="event.stopPropagation();deleteAccountDirect('${acc.id}')">&times;</button>
      </div>
    `;
    listEl.appendChild(card);
  });
}

async function switchAccount(accountId) {
  try {
    const res = await API.setActiveAccount(accountId);
    if (res.success) {
      AppState.activeAccountId = accountId;
      renderTopbar();
      showToast("Active profile updated", "success");
    }
  } catch (e) {
    showToast("Error switching profile", "error");
  }
}

async function deleteAccountDirect(accountId) {
  if (!confirm("Remove this saved profile?")) return;
  try {
    const res = await API.deleteAccount(accountId);
    if (res.success) {
      AppState.accounts = res.accounts || [];
      AppState.activeAccountId = res.active_id || (AppState.accounts[0]?.id || null);
      renderTopbar();
      showToast("Profile removed", "info");
    }
  } catch (e) {
    showToast("Failed to remove profile", "error");
  }
}

function toggleAccountDrawer(forceState) {
  const drawer = document.getElementById("account-slider-drawer");
  const backdrop = document.getElementById("drawer-backdrop");
  if (!drawer) return;

  const isActive = drawer.style.transform === "translateX(0px)";
  const next = typeof forceState === "boolean" ? forceState : !isActive;

  drawer.style.transform = next ? "translateX(0px)" : "translateX(100%)";
  if (backdrop) {
    backdrop.classList.toggle("active", next);
  }
}

// -----------------------------------------------------------------------------
// HERO BACKGROUND WALLPAPER CAROUSEL (IMG 2, 3, 4 + TREE SHADERS)
// -----------------------------------------------------------------------------
const HERO_WALLPAPERS = [
  { name: "Beach Sunset", url: "/assets/bg_beach_sunset.png" },
  { name: "City Skyline", url: "/assets/bg_city_skyline.png" },
  { name: "Snowy Mountains", url: "/assets/bg_snowy_mountains.png" },
  { name: "Forest Tree", url: "/assets/minecraft_tree_shaders.png" }
];
let currentWallpaperIdx = 0;

function initHeroWallpaper() {
  const saved = localStorage.getItem("divine_wallpaper_idx");
  if (saved !== null && !isNaN(parseInt(saved, 10))) {
    currentWallpaperIdx = parseInt(saved, 10) % HERO_WALLPAPERS.length;
  }
  applyHeroWallpaper();
}

function applyHeroWallpaper() {
  const wp = HERO_WALLPAPERS[currentWallpaperIdx];
  const hero = document.getElementById("home-hero-container");
  const label = document.getElementById("hero-wallpaper-name");
  if (hero) {
    hero.style.backgroundImage = `linear-gradient(135deg, rgba(9, 10, 15, 0.84) 0%, rgba(9, 10, 15, 0.65) 45%, rgba(9, 10, 15, 0.9) 100%), url('${wp.url}')`;
  }
  if (label) {
    label.textContent = wp.name;
  }
}

function cycleHeroBackground() {
  currentWallpaperIdx = (currentWallpaperIdx + 1) % HERO_WALLPAPERS.length;
  localStorage.setItem("divine_wallpaper_idx", currentWallpaperIdx);
  applyHeroWallpaper();
  showToast(`Wallpaper switched to ${HERO_WALLPAPERS[currentWallpaperIdx].name}`, "info");
}

// -----------------------------------------------------------------------------
function getFilteredSliderInstances() {
  return AppState.instances || [];
}

function renderHomeSlider(slideDir = "") {
  const instances = getFilteredSliderInstances();
  const nameEl = document.getElementById("hero-slider-name");
  const verEl = document.getElementById("hero-slider-version");
  const loaderEl = document.getElementById("hero-slider-loader");
  const modsEl = document.getElementById("hero-slider-mods");
  const ramEl = document.getElementById("hero-slider-ram");
  const dotsEl = document.getElementById("hero-slider-dots");
  const infoBox = document.getElementById("hero-slider-info-box");
  const playText = document.getElementById("hero-launch-text");

  if (instances.length === 0) {
    AppState.activeInstanceId = null;
    if (nameEl) nameEl.textContent = "No Instances Created";
    if (verEl) verEl.textContent = "Create an Instance";
    if (loaderEl) loaderEl.textContent = "READY";
    if (modsEl) modsEl.textContent = "0 Mods";
    if (ramEl) ramEl.textContent = "4096 MB RAM";
    if (dotsEl) dotsEl.innerHTML = "";
    if (playText && !AppState.isGameRunning) {
      playText.textContent = "+ CREATE INSTANCE";
    }
    return;
  }

  if (AppState.sliderIndex < 0 || AppState.sliderIndex >= instances.length) {
    AppState.sliderIndex = 0;
  }

  const current = instances[AppState.sliderIndex];
  AppState.activeInstanceId = current.id;

  // Trigger smooth slide animation
  if (infoBox && slideDir) {
    infoBox.classList.remove("sliding-next", "sliding-prev");
    void infoBox.offsetWidth; // Force reflow
    infoBox.classList.add(slideDir === "next" ? "sliding-next" : "sliding-prev");
  }

  if (nameEl) nameEl.textContent = current.name || "Minecraft Instance";
  if (verEl) verEl.textContent = current.mc_version || "1.21.11";
  if (loaderEl) loaderEl.textContent = (current.loader || "vanilla").toUpperCase();
  if (modsEl) modsEl.textContent = `${current.mods_count || 0} Mods`;
  if (ramEl) ramEl.textContent = `${current.ram_mb || 4096} MB RAM`;
  if (playText && !AppState.isGameRunning) {
    playText.textContent = "PLAY MINECRAFT";
  }

  // Render Indicator Dots
  if (dotsEl) {
    dotsEl.innerHTML = "";
    instances.forEach((inst, idx) => {
      const dot = document.createElement("div");
      dot.className = `slider-dot ${idx === AppState.sliderIndex ? 'active' : ''}`;
      dot.onclick = () => {
        const dir = idx > AppState.sliderIndex ? "next" : "prev";
        AppState.sliderIndex = idx;
        renderHomeSlider(dir);
      };
      dotsEl.appendChild(dot);
    });
  }
}

function slideInstancePrev() {
  window.soundEngine?.playClick?.();
  const count = getFilteredSliderInstances().length;
  if (count <= 1) return;
  AppState.sliderIndex = (AppState.sliderIndex - 1 + count) % count;
  renderHomeSlider("prev");
}

function slideInstanceNext() {
  window.soundEngine?.playClick?.();
  const count = getFilteredSliderInstances().length;
  if (count <= 1) return;
  AppState.sliderIndex = (AppState.sliderIndex + 1) % count;
  renderHomeSlider("next");
}

function updatePlayButtonVisuals(isRunning, isLaunching) {
  const btn = document.getElementById("hero-launch-btn");
  const text = document.getElementById("hero-launch-text");
  const icon = document.getElementById("hero-launch-icon");
  if (!btn || !text || !icon) return;

  AppState.isGameRunning = isRunning || isLaunching;

  if (isRunning) {
    btn.className = "hero-launch-btn stop";
    text.textContent = "STOP MINECRAFT";
    icon.innerHTML = `<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>`;
  } else if (isLaunching) {
    btn.className = "hero-launch-btn stop";
    text.textContent = "LAUNCHING...";
    icon.innerHTML = `<path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83" stroke="currentColor" stroke-width="2"/>`;
  } else {
    btn.className = "hero-launch-btn";
    text.textContent = "PLAY MINECRAFT";
    icon.innerHTML = `<path d="M8 5v14l11-7z"/>`;
  }
}

async function handleHeroPlayButtonClick() {
  window.soundEngine?.playClick?.();

  if (AppState.isGameRunning) {
    try {
      showToast("Terminating Minecraft process...", "info");
      const res = await API.stopGame(AppState.activeInstanceId);
      if (res.success) {
        updatePlayButtonVisuals(false, false);
        showToast("Minecraft stopped.", "success");
      }
    } catch (e) {
      showToast("Error stopping game process", "error");
    }
    return;
  }

  if (!AppState.activeInstanceId || (AppState.instances || []).length === 0) {
    openCreateInstanceModal();
    return;
  }

  updatePlayButtonVisuals(false, true);
  showToast("Initializing launch sequence...", "info");

  try {
    const res = await API.launchGame(AppState.activeInstanceId);
    if (res.success) {
      openGameConsole(AppState.activeInstanceId);
      startLaunchStatusPolling();
    } else {
      updatePlayButtonVisuals(false, false);
      showToast(res.error || "Failed to launch Minecraft", "error");
    }
  } catch (err) {
    updatePlayButtonVisuals(false, false);
    showToast("Launch failed: " + err.message, "error");
  }
}


let launchPollInterval = null;

let launcherMenuMode = "divine"; // "divine" or "custom"

function setLauncherMenuMode(mode) {
  launcherMenuMode = mode;
  const btnDivine = document.getElementById("mode-btn-divine");
  const btnCustom = document.getElementById("mode-btn-custom");
  const title = document.getElementById("home-main-title");
  const subtitle = document.getElementById("home-main-subtitle");
  const quickPlay = document.querySelector(".quick-play-wrapper");
  const leftArrow = document.querySelector(".slider-nav-arrow:first-child");
  const rightArrow = document.querySelector(".slider-nav-arrow:last-child");

  if (mode === "divine") {
    if (btnDivine) {
      btnDivine.className = "btn btn-sm btn-primary";
      btnDivine.style.background = "";
    }
    if (btnCustom) {
      btnCustom.className = "btn btn-sm btn-secondary";
      btnCustom.style.background = "transparent";
      btnCustom.style.border = "none";
    }
    if (title) title.textContent = "Divine Client (1.21.11)";
    if (subtitle) subtitle.textContent = "Official High-Performance Client Edition with built-in QoL mods and cloaks.";

    const divineInst = (AppState.instances || []).find(i => i.is_divine_exclusive || i.id.includes("divine") || i.name.includes("Divine"));
    if (divineInst) {
      AppState.activeInstanceId = divineInst.id;
    }
    AppState.sliderIndex = 0;
    renderHomeSlider();

    const playText = document.getElementById("hero-launch-text");
    if (playText && !AppState.isGameRunning) {
      playText.textContent = "PLAY DIVINE CLIENT";
    }
    if (quickPlay) quickPlay.style.display = "none";
    if (leftArrow) leftArrow.style.visibility = "hidden";
    if (rightArrow) rightArrow.style.visibility = "hidden";
  } else {
    if (btnCustom) {
      btnCustom.className = "btn btn-sm btn-primary";
      btnCustom.style.background = "";
      btnCustom.style.border = "";
    }
    if (btnDivine) {
      btnDivine.className = "btn btn-sm btn-secondary";
      btnDivine.style.background = "transparent";
      btnDivine.style.border = "none";
    }
    if (title) title.textContent = "All Instances";
    if (subtitle) subtitle.textContent = "Select or create custom instances across Vanilla, Forge, and Modpacks.";

    if (quickPlay) quickPlay.style.display = "flex";
    if (leftArrow) leftArrow.style.visibility = "visible";
    if (rightArrow) rightArrow.style.visibility = "visible";

    AppState.sliderIndex = 0;
    renderHomeSlider();

    const playText = document.getElementById("hero-launch-text");
    if (playText && !AppState.isGameRunning) {
      playText.textContent = "PLAY MINECRAFT";
    }
  }
}

function startLaunchStatusPolling() {
  if (launchPollInterval) clearInterval(launchPollInterval);

  launchPollInterval = setInterval(async () => {
    try {
      const st = await API.getLaunchStatus();
      if (!st) return;

      if (st.status === "launching") {
        updatePlayButtonVisuals(false, true);
        const stageText = st.stage || "Preparing game...";
        const prog = st.progress || 0;
        const btnSub = document.querySelector("#home-play-btn .play-btn-subtitle");
        if (btnSub) btnSub.textContent = prog > 0 ? `${stageText} (${prog}%)` : stageText;
      } else if (st.status === "running") {
        updatePlayButtonVisuals(true, false);
        const btnSub = document.querySelector("#home-play-btn .play-btn-subtitle");
        if (btnSub) btnSub.textContent = "Click to Stop Game";
      } else if (st.status === "idle") {
        updatePlayButtonVisuals(false, false);
        clearInterval(launchPollInterval);
        launchPollInterval = null;
      } else if (st.status === "error") {
        updatePlayButtonVisuals(false, false);
        showToast(st.error || "Launch failed", "error");
        clearInterval(launchPollInterval);
        launchPollInterval = null;
      }
    } catch (e) {
      console.warn("Launch status poll notice:", e);
    }
  }, 750);
}

function renderAnnouncements() {
  const grid = document.getElementById("news-grid");
  if (!grid) return;

  const news = AppState.news || [];
  if (news.length === 0) {
    grid.innerHTML = `
      <div class="news-card">
        <div style="font-size: 13.5px; font-weight: 800; color: #ffffff; margin-bottom: 4px;">Divine Client v5.0.0 Release</div>
        <div style="font-size: 12px; color: #94a3b8; line-height: 1.5;">Welcome to the high-performance obsidian edition with Modrinth modpack installer, dedicated server tunneling, and collaborator access control.</div>
      </div>
    `;
    return;
  }

  grid.innerHTML = "";
  news.slice(0, 3).forEach(item => {
    const card = document.createElement("div");
    card.className = "news-card";
    card.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
        <span style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(item.title || "Announcement")}</span>
        <span class="badge-tag">${escapeHtml(item.tag || "Update")}</span>
      </div>
      <div style="font-size: 12px; color: #94a3b8; line-height: 1.5;">${escapeHtml(item.body || "")}</div>
    `;
    grid.appendChild(card);
  });
}

function renderQuickFriends() {
  const container = document.getElementById("home-quick-friends-list");
  if (!container) return;

  const friends = AppState.friends || [];
  if (friends.length === 0) {
    container.innerHTML = `<div style="text-align: center; font-size: 12px; color: #94a3b8; padding: 8px;">No friends added yet.</div>`;
    return;
  }

  container.innerHTML = "";
  friends.slice(0, 4).forEach(f => {
    const row = document.createElement("div");
    row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 6px 0;";
    row.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px;">
        <img src="${f.avatar_url || 'https://minotar.net/helm/' + encodeURIComponent(f.username) + '/32.png'}" onerror="this.onerror=null;this.src='/assets/ui_account.png';" style="width: 24px; height: 24px; border-radius: 50%;">
        <span style="font-size: 12.5px; font-weight: 700; color: #ffffff;">${escapeHtml(f.username)}</span>
      </div>
      <span style="font-size: 10.5px; color: #22c55e; font-weight: 700;">${f.presence === 'in_game' ? 'IN GAME' : 'ONLINE'}</span>
    `;
    container.appendChild(row);
  });
}

// -----------------------------------------------------------------------------
// MODPACK STORE (MODPACKS ONLY • MATCHING IMAGE-1.PNG)
// -----------------------------------------------------------------------------
function toggleStoreFilter(group, value, element) {
  window.soundEngine?.playClick?.();
  AppState.storeFilters[group] = value;

  const parent = element.parentElement;
  if (parent) {
    parent.querySelectorAll(".filter-pill").forEach(p => p.classList.remove("active"));
  }
  element.classList.add("active");

  fetchStoreModpacks();
}

function setStoreSource(source, element) {
  window.soundEngine?.playClick?.();
  AppState.storeFilters.source = source;
  document.querySelectorAll(".store-source-tab").forEach(t => t.classList.remove("active"));
  element.classList.add("active");
  fetchStoreModpacks();
}

function debounceStoreSearch() {
  clearTimeout(AppState.storeDebounceTimer);
  AppState.storeDebounceTimer = setTimeout(() => {
    const input = document.getElementById("store-search-input");
    AppState.storeFilters.query = input ? input.value.trim() : "";
    fetchStoreModpacks();
  }, 350);
}

async function fetchStoreModpacks() {
  const listEl = document.getElementById("store-modpack-list");
  if (!listEl) return;

  const sortSelect = document.getElementById("store-sort-select");
  const index = sortSelect ? sortSelect.value : "downloads";
  const cat = AppState.storeFilters.category === "all" ? "" : AppState.storeFilters.category;
  const loader = AppState.storeFilters.loader === "all" ? "" : AppState.storeFilters.loader;
  const ver = AppState.storeFilters.version === "all" ? "" : AppState.storeFilters.version;
  const query = AppState.storeFilters.query;

  listEl.innerHTML = `<div style="text-align: center; padding: 40px; color: #94a3b8; font-size: 13.5px;">Searching modpacks database...</div>`;

  try {
    const params = new URLSearchParams({
      q: query,
      version: ver,
      loader: loader,
      category: cat,
      project_type: "modpack",
      index: index,
      limit: 25
    });

    const res = await fetch(`/api/modrinth/modpacks/search?${params.toString()}`);
    const data = await res.json();
    const hits = data.hits || [];

    if (hits.length === 0) {
      listEl.innerHTML = `
        <div class="card-panel" style="text-align: center; padding: 48px;">
          <div style="font-size: 15px; font-weight: 800; color: #ffffff; margin-bottom: 6px;">No Modpacks Found</div>
          <p style="font-size: 12.5px; color: #94a3b8;">Try clearing some filters or searching for different keywords.</p>
        </div>
      `;
      return;
    }

    listEl.innerHTML = "";
    hits.forEach(item => {
      const card = document.createElement("div");
      card.className = "store-card";

      const iconUrl = item.icon_url || "/assets/ui_modpack.png";
      const title = item.title || item.slug || "Modpack";
      const desc = item.description || "Minecraft optimized modpack with custom shaders and performance tweaks.";
      const author = item.author || "Community";
      const downloads = formatDownloadsNumber(item.downloads || 0);

      card.innerHTML = `
        <div class="store-card-left">
          <img src="${iconUrl}" class="store-card-icon" onerror="this.onerror=null;this.src='/assets/ui_modpack.png';" alt="${escapeHtml(title)}">
          <div class="store-card-info">
            <div class="store-card-title-row">
              <span class="store-card-title">${escapeHtml(title)}</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="#38bdf8"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
            </div>
            <div class="store-card-desc" title="${escapeHtml(desc)}">${escapeHtml(desc)}</div>
            <div class="store-card-tags">
              <span class="badge-tag">${escapeHtml(author)}</span>
              <span class="badge-tag loader">${(loader || 'Fabric').toUpperCase()}</span>
              ${(item.categories || []).slice(0, 2).map(c => `<span class="badge-tag">${escapeHtml(c)}</span>`).join('')}
            </div>
          </div>
        </div>

        <div class="store-card-right">
          <div class="store-card-stats">
            <div>${downloads} downloads</div>
            <div>Updated recently</div>
          </div>
          <div class="store-card-actions">
            <button class="btn btn-secondary btn-sm" onclick="openModpackViewModal('${item.project_id || item.slug}', '${escapeHtml(title)}', '${escapeHtml(desc)}', '${iconUrl}', '${escapeHtml(author)}')">View</button>
            <button class="btn-install-green" onclick="installModpackToInstance('${item.project_id || item.slug}', '${escapeHtml(title)}', '${iconUrl}')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
              <span>Install</span>
            </button>
          </div>
        </div>
      `;
      listEl.appendChild(card);
    });
  } catch (err) {
    listEl.innerHTML = `<div style="color: #ef4444; padding: 20px; text-align: center;">Error loading store: ${err.message}</div>`;
  }
}

function formatDownloadsNumber(num) {
  if (num >= 1000000) return (num / 1000000).toFixed(2) + "M";
  if (num >= 1000) return (num / 1000).toFixed(1) + "K";
  return num.toString();
}

async function openModpackViewModal(projectId, title, desc, iconUrl, author) {
  const modal = document.getElementById("modal-modpack-view");
  const iconEl = document.getElementById("modpack-view-icon");
  const titleEl = document.getElementById("modpack-view-title");
  const descEl = document.getElementById("modpack-view-desc");
  const tagsEl = document.getElementById("modpack-view-tags");
  const modsList = document.getElementById("modpack-view-mods-list");
  const installBtn = document.getElementById("modpack-view-install-btn");

  if (iconEl) iconEl.src = iconUrl || "/assets/ui_modpack.png";
  if (titleEl) titleEl.textContent = title;
  if (descEl) descEl.textContent = desc;
  if (tagsEl) {
    tagsEl.innerHTML = `
      <span class="badge-tag">${escapeHtml(author)}</span>
      <span class="badge-tag loader">FABRIC</span>
      <span class="badge-tag version">1.21.1</span>
      <span class="badge-tag mods">MODPACK</span>
    `;
  }

  if (installBtn) {
    installBtn.onclick = () => {
      closeModal("modal-modpack-view");
      installModpackToInstance(projectId, title, iconUrl);
    };
  }

  if (modsList) modsList.innerHTML = "Fetching modpack dependencies and included mods list...";

  if (modal) modal.classList.add("active");

  try {
    const res = await fetch(`https://api.modrinth.com/v2/project/${projectId}/version`);
    const versions = await res.json();
    if (Array.isArray(versions) && versions.length > 0) {
      const v = versions[0];
      const deps = v.dependencies || [];
      if (deps.length > 0) {
        modsList.innerHTML = `<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">` +
          deps.map(d => `<div style="background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 4px; font-family: monospace;">${escapeHtml(d.project_id || d.version_id || 'Mod Dependency')}</div>`).join('') +
          `</div>`;
      } else {
        modsList.innerHTML = `<div style="color: #cbd5e1;">This modpack includes curated performance mods, shaders, shader support, and pre-tuned configuration overrides.</div>`;
      }
    } else {
      modsList.innerHTML = `<div style="color: #cbd5e1;">Includes complete game configuration, shaders, and fabric optimization suite.</div>`;
    }
  } catch (e) {
    if (modsList) modsList.innerHTML = `<div style="color: #cbd5e1;">Includes full suite of performance and visual optimization mods.</div>`;
  }
}

let currentModpackInstallJob = null;
let modpackInstallPollTimer = null;

async function installModpackToInstance(projectId, name, iconUrl = null) {
  window.soundEngine?.playClick?.();

  const modal = document.getElementById("modal-modpack-progress");
  const titleEl = document.getElementById("modpack-progress-title");
  const subEl = document.getElementById("modpack-progress-subtitle");
  const iconEl = document.getElementById("modpack-progress-icon");
  const pctBadge = document.getElementById("modpack-progress-pct-badge");
  const barFill = document.getElementById("modpack-progress-bar-fill");
  const filesEl = document.getElementById("modpack-progress-files");
  const speedEl = document.getElementById("modpack-progress-speed");
  const etaEl = document.getElementById("modpack-progress-eta");
  const bytesEl = document.getElementById("modpack-progress-bytes");
  const fileEl = document.getElementById("modpack-progress-filename");
  const actionBtn = document.getElementById("modpack-progress-action-btn");
  const cancelBtn = document.getElementById("modpack-progress-cancel-btn");

  if (titleEl) titleEl.textContent = `Downloading ${name}`;
  if (subEl) subEl.textContent = "Connecting to Modrinth and resolving dependencies...";
  if (iconEl) iconEl.src = iconUrl || "/assets/ui_modpack.png";
  if (pctBadge) pctBadge.textContent = "0%";
  if (barFill) barFill.style.width = "0%";
  if (filesEl) filesEl.textContent = "0 files";
  if (speedEl) speedEl.textContent = "0 KB/s";
  if (etaEl) etaEl.textContent = "Calculating...";
  if (bytesEl) bytesEl.textContent = "0 MB / 0 MB";
  if (fileEl) fileEl.textContent = "Preparing modpack manifest...";
  if (actionBtn) actionBtn.style.display = "none";
  if (cancelBtn) {
    cancelBtn.style.display = "inline-flex";
    cancelBtn.textContent = "Cancel";
  }

  if (modal) modal.classList.add("active");
  showToast(`Downloading & installing modpack: ${name}...`, "info");

  if (modpackInstallPollTimer) {
    clearInterval(modpackInstallPollTimer);
    modpackInstallPollTimer = null;
  }

  try {
    const startRes = await API.startInstallModpack(projectId, null, name);
    if (!startRes || !startRes.job_id) {
      if (startRes && startRes.error) {
        showToast(startRes.error, "error");
        if (subEl) subEl.textContent = `Error: ${startRes.error}`;
      }
      return;
    }

    const jobId = startRes.job_id;
    currentModpackInstallJob = jobId;

    modpackInstallPollTimer = setInterval(async () => {
      try {
        const progress = await API.getModpackInstallProgress(jobId);
        if (!progress || progress.error) return;

        const pct = Math.min(100, Math.max(0, progress.percentage || 0));
        if (pctBadge) pctBadge.textContent = `${pct}%`;
        if (barFill) barFill.style.width = `${pct}%`;

        if (filesEl) {
          filesEl.textContent = `${progress.done_files || 0} / ${progress.total_files || '...'}`;
        }
        if (speedEl) {
          speedEl.textContent = progress.speed_formatted || "0 KB/s";
        }
        if (etaEl) {
          etaEl.textContent = progress.eta_formatted || "Calculating...";
        }
        if (bytesEl && progress.total_bytes > 0) {
          const doneMb = (progress.done_bytes / (1024 * 1024)).toFixed(1);
          const totalMb = (progress.total_bytes / (1024 * 1024)).toFixed(1);
          bytesEl.textContent = `${doneMb} MB / ${totalMb} MB`;
        }
        if (fileEl) {
          fileEl.textContent = progress.current_file || progress.message || "Downloading files...";
        }
        if (subEl) {
          subEl.textContent = progress.message || "Downloading modpack files...";
        }

        if (progress.status === "completed") {
          clearInterval(modpackInstallPollTimer);
          modpackInstallPollTimer = null;
          window.soundEngine?.playClick?.();

          if (pctBadge) pctBadge.textContent = "100%";
          if (barFill) barFill.style.width = "100%";
          if (etaEl) etaEl.textContent = "Finished";
          if (subEl) subEl.textContent = "Installation complete!";
          if (fileEl) fileEl.textContent = "All mods, shaders and configuration files installed.";
          if (cancelBtn) cancelBtn.textContent = "Close";
          if (actionBtn) {
            actionBtn.style.display = "inline-flex";
            actionBtn.textContent = "View in Library";
            actionBtn.onclick = () => {
              handleModpackInstallDone(progress.instance);
            };
          }

          showToast(`Modpack '${name}' installed as new instance!`, "success");
          const instData = await API.getInstances();
          AppState.instances = instData.instances || [];
          if (progress.instance) {
            AppState.activeInstanceId = progress.instance.id;
            const newIdx = AppState.instances.findIndex(i => i.id === progress.instance.id);
            if (newIdx !== -1) AppState.sliderIndex = newIdx;
          }
          renderHomeSlider();
        } else if (progress.status === "failed") {
          clearInterval(modpackInstallPollTimer);
          modpackInstallPollTimer = null;
          if (subEl) subEl.textContent = `Installation failed: ${progress.error || 'Unknown error'}`;
          if (fileEl) fileEl.textContent = progress.error || "Failed to download";
          showToast(progress.error || "Failed to install modpack", "error");
        }
      } catch (pollErr) {
        console.error("Progress poll error:", pollErr);
      }
    }, 250);

  } catch (e) {
    showToast("Installation error: " + e.message, "error");
    if (subEl) subEl.textContent = `Error: ${e.message}`;
  }
}

function handleModpackInstallDone(instance = null) {
  closeModal("modal-modpack-progress");
  switchTab("overview");
  if (instance && instance.id) {
    const idx = (AppState.instances || []).findIndex(i => i.id === instance.id);
    if (idx !== -1) {
      AppState.sliderIndex = idx;
      AppState.activeInstanceId = instance.id;
    }
  }
  renderHomeSlider("next");
}

// -----------------------------------------------------------------------------
// DEDICATED INSTANCE EDITOR TAB
// -----------------------------------------------------------------------------
function populateEditorInstanceSelect() {
  const select = document.getElementById("editor-instance-select");
  if (!select) return;

  select.innerHTML = "";
  (AppState.instances || []).forEach(inst => {
    const opt = document.createElement("option");
    opt.value = inst.id;
    opt.textContent = inst.name;
    if (inst.id === (AppState.currentEditorInstanceId || AppState.activeInstanceId)) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });
}

async function loadInstanceIntoEditor(instanceId) {
  if (!instanceId) return;
  AppState.currentEditorInstanceId = instanceId;

  const inst = AppState.instances.find(i => i.id === instanceId);
  const nameInput = document.getElementById("editor-instance-name-input");
  const metaLine = document.getElementById("editor-instance-meta-line");
  const iconImg = document.getElementById("editor-inst-icon-img");
  const ramSlider = document.getElementById("editor-ram-slider");
  const ramDisplay = document.getElementById("editor-ram-display");
  const jvmInput = document.getElementById("editor-custom-jvm-input");
  const javaInput = document.getElementById("editor-custom-java-input");
  const fsToggle = document.getElementById("editor-fullscreen-toggle");

  if (inst) {
    if (nameInput) nameInput.value = inst.name;
    if (metaLine) metaLine.textContent = `Minecraft ${inst.mc_version || '1.21.1'} • ${(inst.loader || 'fabric').toUpperCase()}`;
    if (iconImg) iconImg.src = inst.custom_icon || inst.icon || "/assets/loader_fabric.svg";
    if (ramSlider) ramSlider.value = inst.ram_mb || 4096;
    if (ramDisplay) ramDisplay.textContent = `${inst.ram_mb || 4096} MB`;
    if (jvmInput) jvmInput.value = inst.jvm_args || "";
    if (javaInput) javaInput.value = inst.custom_java_path || "";
    if (fsToggle) fsToggle.checked = !!inst.fullscreen;
  }

  // Fetch installed mods, resource packs, shaders in parallel
  try {
    const [modsRes, rpRes, shaderRes] = await Promise.allSettled([
      API.getInstanceMods(instanceId),
      API.getInstanceResourcePacks(instanceId),
      API.getInstanceShaders(instanceId),
    ]);

    if (modsRes.status === "fulfilled" && modsRes.value) {
      AppState.currentEditorMods = modsRes.value.mods || [];
      renderEditorModsList(AppState.currentEditorMods);
    }
    if (rpRes.status === "fulfilled" && rpRes.value) {
      AppState.currentEditorResourcePacks = rpRes.value.resource_packs || [];
      renderEditorResourcePacksList(AppState.currentEditorResourcePacks);
    }
    if (shaderRes.status === "fulfilled" && shaderRes.value) {
      AppState.currentEditorShaders = shaderRes.value.shaders || [];
      renderEditorShadersList(AppState.currentEditorShaders);
    }
  } catch (e) {
    console.error("Error loading instance assets:", e);
  }
}

function renderEditorModsList(mods) {
  const tbody = document.getElementById("editor-mods-table-body");
  const badge = document.getElementById("editor-mods-count-badge");
  if (!tbody) return;

  if (badge) badge.textContent = `${mods.length} Mods`;

  if (mods.length === 0) {
    tbody.innerHTML = `<div style="text-align: center; padding: 24px; color: #94a3b8; font-size: 13px;">No mods installed in this instance. Click '+ Add Mods from Modrinth'.</div>`;
    return;
  }

  tbody.innerHTML = "";
  mods.forEach(mod => {
    const row = document.createElement("div");
    row.className = "editor-mod-row";
    row.innerHTML = `
      <div style="display: flex; align-items: center; gap: 12px;">
        <label class="toggle-switch">
          <input type="checkbox" ${mod.enabled ? 'checked' : ''} onchange="toggleEditorMod('${escapeHtml(mod.filename)}', this.checked)">
          <span class="toggle-slider"></span>
        </label>
        <div>
          <div style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(mod.name || mod.filename)}</div>
          <div style="font-size: 11px; color: #64748b;">${escapeHtml(mod.filename)} • ${mod.size_human || ''}</div>
        </div>
      </div>
      <button class="btn btn-danger btn-sm" onclick="deleteEditorMod('${escapeHtml(mod.filename)}')">Delete</button>
    `;
    tbody.appendChild(row);
  });
}

function renderEditorResourcePacksList(packs) {
  const container = document.getElementById("editor-resourcepacks-table-body");
  if (!container) return;

  if (packs.length === 0) {
    container.innerHTML = `<div style="text-align: center; padding: 24px; color: #94a3b8; font-size: 13px;">No texture packs installed. Click '+ Add Resource Pack'.</div>`;
    return;
  }

  container.innerHTML = "";
  packs.forEach(pack => {
    const row = document.createElement("div");
    row.className = "editor-mod-row";
    row.innerHTML = `
      <div style="display: flex; align-items: center; gap: 12px;">
        <label class="toggle-switch">
          <input type="checkbox" ${pack.enabled ? 'checked' : ''} onchange="toggleEditorResourcePack('${escapeHtml(pack.filename)}', this.checked)">
          <span class="toggle-slider"></span>
        </label>
        <div>
          <div style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(pack.name || pack.filename)}</div>
          <div style="font-size: 11px; color: #64748b;">${escapeHtml(pack.filename)} • ${pack.size_human || ''}</div>
        </div>
      </div>
      <button class="btn btn-danger btn-sm" onclick="deleteEditorResourcePack('${escapeHtml(pack.filename)}')">Delete</button>
    `;
    container.appendChild(row);
  });
}

function renderEditorShadersList(shaders) {
  const container = document.getElementById("editor-shaders-table-body");
  if (!container) return;

  if (shaders.length === 0) {
    container.innerHTML = `<div style="text-align: center; padding: 24px; color: #94a3b8; font-size: 13px;">No shader packs installed. Click '+ Add Shader Pack'.</div>`;
    return;
  }

  container.innerHTML = "";
  shaders.forEach(shader => {
    const row = document.createElement("div");
    row.className = "editor-mod-row";
    row.innerHTML = `
      <div style="display: flex; align-items: center; gap: 12px;">
        <label class="toggle-switch">
          <input type="checkbox" ${shader.enabled ? 'checked' : ''} onchange="toggleEditorShader('${escapeHtml(shader.filename)}', this.checked)">
          <span class="toggle-slider"></span>
        </label>
        <div>
          <div style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(shader.name || shader.filename)}</div>
          <div style="font-size: 11px; color: #64748b;">${escapeHtml(shader.filename)} • ${shader.size_human || ''}</div>
        </div>
      </div>
      <button class="btn btn-danger btn-sm" onclick="deleteEditorShader('${escapeHtml(shader.filename)}')">Delete</button>
    `;
    container.appendChild(row);
  });
}

function filterEditorModsList(query) {
  const q = (query || "").toLowerCase();
  const filtered = AppState.currentEditorMods.filter(m => (m.name || "").toLowerCase().includes(q) || (m.filename || "").toLowerCase().includes(q));
  renderEditorModsList(filtered);
}

async function toggleEditorMod(filename, enable) {
  try {
    await API.toggleMod(AppState.currentEditorInstanceId, filename, enable);
    showToast(`Mod ${enable ? 'enabled' : 'disabled'}`, "info");
  } catch (e) {
    showToast("Error updating mod state", "error");
  }
}

async function deleteEditorMod(filename) {
  if (!confirm(`Delete mod '${filename}'?`)) return;
  try {
    await API.deleteMod(AppState.currentEditorInstanceId, filename);
    showToast("Mod removed", "info");
    loadInstanceIntoEditor(AppState.currentEditorInstanceId);
  } catch (e) {
    showToast("Failed to delete mod", "error");
  }
}

async function toggleEditorResourcePack(filename, enable) {
  try {
    await API.toggleResourcePack(AppState.currentEditorInstanceId, filename, enable);
    showToast(`Resource pack ${enable ? 'enabled' : 'disabled'}`, "info");
  } catch (e) {
    showToast("Error toggling resource pack", "error");
  }
}

async function deleteEditorResourcePack(filename) {
  if (!confirm(`Delete resource pack '${filename}'?`)) return;
  try {
    await API.deleteResourcePack(AppState.currentEditorInstanceId, filename);
    showToast("Resource pack removed", "info");
    loadInstanceIntoEditor(AppState.currentEditorInstanceId);
  } catch (e) {
    showToast("Failed to delete resource pack", "error");
  }
}

async function toggleEditorShader(filename, enable) {
  try {
    await API.toggleShader(AppState.currentEditorInstanceId, filename, enable);
    showToast(`Shader pack ${enable ? 'enabled' : 'disabled'}`, "info");
  } catch (e) {
    showToast("Error toggling shader pack", "error");
  }
}

async function deleteEditorShader(filename) {
  if (!confirm(`Delete shader pack '${filename}'?`)) return;
  try {
    await API.deleteShader(AppState.currentEditorInstanceId, filename);
    showToast("Shader pack removed", "info");
    loadInstanceIntoEditor(AppState.currentEditorInstanceId);
  } catch (e) {
    showToast("Failed to delete shader pack", "error");
  }
}

// -----------------------------------------------------------------------------
// FIX MODS COMPATIBILITY (FABRIC + IRIS + SODIUM AUTO-RESOLVER)
// -----------------------------------------------------------------------------
async function fixCurrentEditorModsCompatibility() {
  window.soundEngine?.playClick?.();
  const iid = AppState.currentEditorInstanceId;
  if (!iid) return;

  showToast("Scanning mods and fixing Fabric + Iris + Sodium compatibility...", "info");
  try {
    const res = await API.fixModsCompatibility(iid);
    if (res.success) {
      showToast(res.message || "Mods version compatibility fixed successfully!", "success");
      loadInstanceIntoEditor(iid);
    } else {
      showToast(res.error || "Failed to fix mod compatibility", "error");
    }
  } catch (e) {
    showToast("Error running mod compatibility fix", "error");
  }
}

// -----------------------------------------------------------------------------
// ADD MODS / RESOURCE PACKS / SHADERS MODALS (FROM MODRINTH)
// -----------------------------------------------------------------------------
function openModSearchModalForEditor() {
  const modal = document.getElementById("modal-add-mod");
  if (modal) modal.classList.add("active");
  searchModsForEditor("");
}

function debounceModSearch() {
  clearTimeout(AppState.modDebounceTimer);
  AppState.modDebounceTimer = setTimeout(() => {
    const query = document.getElementById("add-mod-search-input")?.value.trim() || "";
    searchModsForEditor(query);
  }, 350);
}

async function searchModsForEditor(query) {
  const results = document.getElementById("add-mod-results-list");
  if (!results) return;
  results.innerHTML = `<div style="text-align:center;padding:20px;color:#94a3b8;">Searching mods...</div>`;

  const inst = AppState.instances.find(i => i.id === AppState.currentEditorInstanceId);
  const mcVer = inst?.mc_version || "1.21.1";
  const loader = inst?.loader || "fabric";

  try {
    const data = await API.searchModrinth(query, "", loader, mcVer, "mod", "downloads", 20);
    const hits = data.hits || [];
    if (hits.length === 0) {
      results.innerHTML = `<div style="text-align:center;padding:20px;color:#94a3b8;">No matching mods found.</div>`;
      return;
    }
    results.innerHTML = "";
    hits.forEach(m => {
      const row = document.createElement("div");
      row.className = "card-panel";
      row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 10px 14px;";
      row.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px;">
          <img src="${m.icon_url || '/assets/ui_modpack.png'}" style="width: 32px; height: 32px; border-radius: 6px;">
          <div>
            <div style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(m.title)}</div>
            <div style="font-size: 11px; color: #94a3b8;">${escapeHtml(m.author)} • ${formatDownloadsNumber(m.downloads || 0)} downloads</div>
          </div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="installModDirectToInstance('${m.project_id}', '${escapeHtml(m.title)}')">+ Add</button>
      `;
      results.appendChild(row);
    });
  } catch (e) {
    results.innerHTML = `<div style="color:#ef4444;text-align:center;">Error searching mods.</div>`;
  }
}

async function installModDirectToInstance(projectId, title) {
  showToast(`Installing ${title}...`, "info");
  try {
    const res = await API.installModrinth(projectId, AppState.currentEditorInstanceId, null, "mod");
    if (res.success) {
      showToast(`${title} installed!`, "success");
      loadInstanceIntoEditor(AppState.currentEditorInstanceId);
    } else {
      showToast(res.error || "Installation failed", "error");
    }
  } catch (e) {
    showToast("Error installing mod", "error");
  }
}

function openResourcepackSearchModal() {
  const modal = document.getElementById("modal-add-resourcepack");
  if (modal) modal.classList.add("active");
  searchResourcepacksForEditor("");
}

function debounceRpSearch() {
  clearTimeout(AppState.rpDebounceTimer);
  AppState.rpDebounceTimer = setTimeout(() => {
    const query = document.getElementById("add-rp-search-input")?.value.trim() || "";
    searchResourcepacksForEditor(query);
  }, 350);
}

async function searchResourcepacksForEditor(query) {
  const results = document.getElementById("add-rp-results-list");
  if (!results) return;
  results.innerHTML = `<div style="text-align:center;padding:20px;color:#94a3b8;">Searching resource packs...</div>`;

  try {
    const data = await API.searchModrinth(query, "", "", "", "resourcepack", "downloads", 20);
    const hits = data.hits || [];
    if (hits.length === 0) {
      results.innerHTML = `<div style="text-align:center;padding:20px;color:#94a3b8;">No matching resource packs found.</div>`;
      return;
    }
    results.innerHTML = "";
    hits.forEach(rp => {
      const row = document.createElement("div");
      row.className = "card-panel";
      row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 10px 14px;";
      row.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px;">
          <img src="${rp.icon_url || '/assets/ui_picture.png'}" style="width: 32px; height: 32px; border-radius: 6px;">
          <div>
            <div style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(rp.title)}</div>
            <div style="font-size: 11px; color: #94a3b8;">${escapeHtml(rp.author)} • ${formatDownloadsNumber(rp.downloads || 0)} downloads</div>
          </div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="installResourcepackDirectToInstance('${rp.project_id}', '${escapeHtml(rp.title)}')">+ Add</button>
      `;
      results.appendChild(row);
    });
  } catch (e) {
    results.innerHTML = `<div style="color:#ef4444;text-align:center;">Error searching resource packs.</div>`;
  }
}

async function installResourcepackDirectToInstance(projectId, title) {
  showToast(`Downloading resource pack: ${title}...`, "info");
  try {
    const res = await API.installModrinth(projectId, AppState.currentEditorInstanceId, null, "resourcepack");
    if (res.success) {
      showToast(`${title} added to instance!`, "success");
      loadInstanceIntoEditor(AppState.currentEditorInstanceId);
    }
  } catch (e) {
    showToast("Error installing resource pack", "error");
  }
}

async function handleResourcePackUpload(input) {
  const file = input.files?.[0];
  if (!file || !AppState.currentEditorInstanceId) return;

  const formData = new FormData();
  formData.append("file", file);

  showToast(`Uploading ${file.name}...`, "info");
  try {
    const res = await fetch(`/api/instances/${encodeURIComponent(AppState.currentEditorInstanceId)}/resourcepacks/upload`, {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Resource pack uploaded!`, "success");
      loadInstanceIntoEditor(AppState.currentEditorInstanceId);
      closeModal("modal-add-resourcepack");
    }
  } catch (e) {
    showToast("Upload failed", "error");
  }
}

function openShaderSearchModal() {
  const modal = document.getElementById("modal-add-shader");
  if (modal) modal.classList.add("active");
  searchShadersForEditor("");
}

function debounceShaderSearch() {
  clearTimeout(AppState.shaderDebounceTimer);
  AppState.shaderDebounceTimer = setTimeout(() => {
    const query = document.getElementById("add-shader-search-input")?.value.trim() || "";
    searchShadersForEditor(query);
  }, 350);
}

async function searchShadersForEditor(query) {
  const results = document.getElementById("add-shader-results-list");
  if (!results) return;
  results.innerHTML = `<div style="text-align:center;padding:20px;color:#94a3b8;">Searching shaders...</div>`;

  try {
    const data = await API.searchModrinth(query, "", "", "", "shader", "downloads", 20);
    const hits = data.hits || [];
    if (hits.length === 0) {
      results.innerHTML = `<div style="text-align:center;padding:20px;color:#94a3b8;">No matching shaders found.</div>`;
      return;
    }
    results.innerHTML = "";
    hits.forEach(sh => {
      const row = document.createElement("div");
      row.className = "card-panel";
      row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 10px 14px;";
      row.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px;">
          <img src="${sh.icon_url || '/assets/ui_picture.png'}" style="width: 32px; height: 32px; border-radius: 6px;">
          <div>
            <div style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(sh.title)}</div>
            <div style="font-size: 11px; color: #94a3b8;">${escapeHtml(sh.author)} • ${formatDownloadsNumber(sh.downloads || 0)} downloads</div>
          </div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="installShaderDirectToInstance('${sh.project_id}', '${escapeHtml(sh.title)}')">+ Add</button>
      `;
      results.appendChild(row);
    });
  } catch (e) {
    results.innerHTML = `<div style="color:#ef4444;text-align:center;">Error searching shaders.</div>`;
  }
}

async function installShaderDirectToInstance(projectId, title) {
  showToast(`Downloading shader: ${title}...`, "info");
  try {
    const res = await API.installModrinth(projectId, AppState.currentEditorInstanceId, null, "shader");
    if (res.success) {
      showToast(`${title} installed!`, "success");
      loadInstanceIntoEditor(AppState.currentEditorInstanceId);
    }
  } catch (e) {
    showToast("Error installing shader", "error");
  }
}

async function handleShaderUpload(input) {
  const file = input.files?.[0];
  if (!file || !AppState.currentEditorInstanceId) return;

  const formData = new FormData();
  formData.append("file", file);

  showToast(`Uploading shader ${file.name}...`, "info");
  try {
    const res = await fetch(`/api/instances/${encodeURIComponent(AppState.currentEditorInstanceId)}/shaders/upload`, {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Shader uploaded!`, "success");
      loadInstanceIntoEditor(AppState.currentEditorInstanceId);
      closeModal("modal-add-shader");
    }
  } catch (e) {
    showToast("Upload failed", "error");
  }
}

function switchEditorSubpane(paneName, element) {
  window.soundEngine?.playClick?.();
  document.querySelectorAll(".editor-subtab-btn").forEach(b => b.classList.remove("active"));
  element.classList.add("active");

  document.querySelectorAll(".editor-subpane").forEach(p => p.classList.remove("active"));
  document.getElementById(`editor-subpane-${paneName}`)?.classList.add("active");
}

function triggerCustomIconPicker() {
  document.getElementById("editor-custom-icon-file")?.click();
}

async function uploadInstanceIconFile(input) {
  const file = input.files?.[0];
  if (!file || !AppState.currentEditorInstanceId) return;

  const reader = new FileReader();
  reader.onload = async (e) => {
    const dataUrl = e.target.result;
    document.getElementById("editor-inst-icon-img").src = dataUrl;
    try {
      await API.updateInstance(AppState.currentEditorInstanceId, { custom_icon: dataUrl });
      showToast("Instance icon updated!", "success");
    } catch (err) {}
  };
  reader.readAsDataURL(file);
}

function updateEditorRamDisplay(val) {
  const display = document.getElementById("editor-ram-display");
  if (display) display.textContent = `${val} MB`;
}

async function saveCurrentEditorInstance() {
  const iid = AppState.currentEditorInstanceId;
  if (!iid) return;

  const name = document.getElementById("editor-instance-name-input")?.value.trim();
  const ram = parseInt(document.getElementById("editor-ram-slider")?.value || 4096);
  const jvm = document.getElementById("editor-custom-jvm-input")?.value.trim();
  const javaPath = document.getElementById("editor-custom-java-input")?.value.trim();
  const fullscreen = document.getElementById("editor-fullscreen-toggle")?.checked;

  try {
    const res = await API.updateInstance(iid, {
      name: name,
      ram_mb: ram,
      jvm_args: jvm,
      custom_java_path: javaPath,
      fullscreen: fullscreen
    });
    if (res.success) {
      showToast("Instance settings saved!", "success");
      const instData = await API.getInstances();
      AppState.instances = instData.instances || [];
      renderHomeSlider();
    }
  } catch (e) {
    showToast("Error saving instance", "error");
  }
}

async function deleteCurrentEditorInstance() {
  const iid = AppState.currentEditorInstanceId;
  if (!iid) return;
  if (!confirm("Are you sure you want to permanently delete this instance and its worlds?")) return;

  try {
    const res = await API.deleteInstance(iid);
    if (res.success) {
      showToast("Instance deleted.", "info");
      const instData = await API.getInstances();
      AppState.instances = instData.instances || [];
      AppState.activeInstanceId = AppState.instances[0]?.id || null;
      renderHomeSlider();
      switchTab("overview");
    }
  } catch (e) {
    showToast("Failed to delete instance", "error");
  }
}

// -----------------------------------------------------------------------------
// FRIENDS & PLAYER NETWORK (DATABASE VERIFIED • NO DISCORD • NO FAKE FRIENDS)
// -----------------------------------------------------------------------------
function switchFriendsSubtab(subtab, element) {
  window.soundEngine?.playClick?.();
  document.querySelectorAll(".friends-tab-btn").forEach(b => b.classList.remove("active"));
  element.classList.add("active");

  document.querySelectorAll(".friends-subpane").forEach(p => p.style.display = "none");
  const target = document.getElementById(`friends-subpane-${subtab}`);
  if (target) target.style.display = "block";

  if (subtab === "friends") renderFriendsList();
  else if (subtab === "pending") renderPendingRequests();
  else if (subtab === "shared-servers") renderSharedServersList();
}

function renderFriendsView() {
  renderFriendsList();
  renderPendingRequests();
  renderSharedServersList();
}

function renderFriendsList() {
  const grid = document.getElementById("friends-full-grid");
  if (!grid) return;

  const friends = AppState.friends || [];
  if (friends.length === 0) {
    grid.innerHTML = `<div class="card-panel" style="grid-column: 1/-1; text-align: center; padding: 40px; color: #94a3b8;">No friends added yet. Click '+ Add Friend' to search the player network.</div>`;
    return;
  }

  grid.innerHTML = "";
  friends.forEach(f => {
    const card = document.createElement("div");
    card.className = "friend-card";
    const skinUrl = f.avatar_url || `https://minotar.net/helm/${encodeURIComponent(f.username)}/36.png`;

    card.innerHTML = `
      <div style="display: flex; align-items: center; gap: 12px;">
        <img src="${skinUrl}" onerror="this.onerror=null;this.src='/assets/ui_account.png';" style="width: 36px; height: 36px; border-radius: 50%;">
        <div>
          <div style="font-size: 14px; font-weight: 800; color: #ffffff;">${escapeHtml(f.username)}</div>
          <div style="font-size: 11px; color: ${f.presence === 'in_game' ? '#38bdf8' : '#22c55e'}; font-weight: 700;">${escapeHtml(f.presence_detail || 'Online in Divine Client')}</div>
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 6px;">
        <button class="btn btn-secondary btn-sm" onclick="showToast('Invited ${escapeHtml(f.username)} to server!', 'success')">Invite</button>
        <button class="btn btn-secondary btn-sm" style="color: #ef4444;" onclick="removeFriendDirect('${f.id}')">&times;</button>
      </div>
    `;
    grid.appendChild(card);
  });
}

function renderPendingRequests() {
  const container = document.getElementById("friends-pending-container");
  const tabBtn = document.getElementById("friends-pending-tab-btn");
  if (!container) return;

  const incoming = AppState.incomingRequests || [];
  const outgoing = AppState.outgoingRequests || [];
  const totalPending = incoming.length + outgoing.length;

  if (tabBtn) tabBtn.textContent = `Pending Requests (${totalPending})`;

  if (totalPending === 0) {
    container.innerHTML = `<div class="card-panel" style="text-align: center; padding: 32px; color: #94a3b8;">No incoming or outgoing friend requests.</div>`;
    return;
  }

  container.innerHTML = "";

  if (incoming.length > 0) {
    const incHeader = document.createElement("div");
    incHeader.style.cssText = "font-size: 12px; font-weight: 800; color: #cbd5e1; text-transform: uppercase;";
    incHeader.textContent = "Incoming Requests";
    container.appendChild(incHeader);

    incoming.forEach(req => {
      const row = document.createElement("div");
      row.className = "card-panel";
      row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;";
      row.innerHTML = `
        <div style="display: flex; align-items: center; gap: 12px;">
          <img src="${req.avatar_url || 'https://minotar.net/helm/' + encodeURIComponent(req.username) + '/36.png'}" style="width: 32px; height: 32px; border-radius: 50%;">
          <div>
            <div style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(req.username)}</div>
            <div style="font-size: 11px; color: #94a3b8;">${escapeHtml(req.note || 'Sent a friend request')}</div>
          </div>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn btn-primary btn-sm" onclick="acceptFriendRequestDirect('${req.id}', '${escapeHtml(req.username)}')">Accept</button>
          <button class="btn btn-danger btn-sm" onclick="declineFriendRequestDirect('${req.id}', '${escapeHtml(req.username)}')">Decline</button>
        </div>
      `;
      container.appendChild(row);
    });
  }

  if (outgoing.length > 0) {
    const outHeader = document.createElement("div");
    outHeader.style.cssText = "font-size: 12px; font-weight: 800; color: #cbd5e1; text-transform: uppercase; margin-top: 12px;";
    outHeader.textContent = "Outgoing Sent Requests";
    container.appendChild(outHeader);

    outgoing.forEach(req => {
      const row = document.createElement("div");
      row.className = "card-panel";
      row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;";
      row.innerHTML = `
        <div style="display: flex; align-items: center; gap: 12px;">
          <img src="${req.avatar_url || 'https://minotar.net/helm/' + encodeURIComponent(req.username) + '/36.png'}" style="width: 32px; height: 32px; border-radius: 50%;">
          <div>
            <div style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(req.username)}</div>
            <div style="font-size: 11px; color: #94a3b8;">Request pending database confirmation</div>
          </div>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="declineFriendRequestDirect('${req.id}', '${escapeHtml(req.username)}')">Cancel</button>
      `;
      container.appendChild(row);
    });
  }
}

function renderSharedServersList() {
  const grid = document.getElementById("friends-shared-servers-grid");
  if (!grid) return;

  const servers = AppState.servers || [];
  grid.innerHTML = "";

  if (servers.length === 0) {
    grid.innerHTML = `<div class="card-panel" style="grid-column: 1/-1; text-align: center; padding: 36px; color: #94a3b8;">No shared multiplayer servers found. Ask friends to grant you collaborator access on their servers!</div>`;
    return;
  }

  servers.forEach(s => {
    const card = document.createElement("div");
    card.className = "card-panel";
    const isOnline = s.status === "running" || s.status === "online";
    const address = s.public_address || (s.port ? `localhost:${s.port}` : "127.0.0.1:25565");
    const motd = s.motd || "created by Divine client servers";
    const accessUsers = s.access_users || [];
    card.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 14.5px; font-weight: 800; color: #ffffff;">${escapeHtml(s.name)}</span>
          <span class="badge-tag loader">${escapeHtml(s.loader || 'Paper').toUpperCase()}</span>
          <span class="badge-tag version">${escapeHtml(s.mc_version || '1.21.4')}</span>
        </div>
        <span class="badge-tag ${isOnline ? 'mods' : ''}" style="${isOnline ? 'background: rgba(34,197,94,0.2); color: #22c55e; border-color: rgba(34,197,94,0.4);' : 'background: rgba(239,68,68,0.15); color: #ef4444; border-color: rgba(239,68,68,0.3);'}">${isOnline ? 'ONLINE' : 'STOPPED'}</span>
      </div>
      <div style="font-size: 11.5px; color: #38bdf8; font-style: italic; margin-bottom: 8px;">
        ${escapeHtml(motd)}
      </div>
      <div style="font-size: 12px; color: #cbd5e1; font-family: monospace; margin-bottom: 12px; background: rgba(0,0,0,0.35); padding: 7px 10px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center;">
        <span>${escapeHtml(address)}</span>
        <button class="btn btn-secondary btn-sm" style="padding: 2px 8px; font-size: 10px;" onclick="copyToClipboard('${escapeHtml(address)}')">Copy IP</button>
      </div>
      <div style="display: flex; gap: 8px;">
        <button class="btn btn-primary btn-sm" style="flex: 1;" onclick="openDedicatedServerAppWindow('${s.id}', '${escapeHtml(s.name)}')">Manage Console &amp; Files</button>
        <button class="btn btn-secondary btn-sm" onclick="openServerAccessModal('${s.id}', '${escapeHtml(s.name)}')">Access (${accessUsers.length})</button>
      </div>
    `;
    grid.appendChild(card);
  });
}

function openAddFriendModal() {
  const modal = document.getElementById("modal-add-friend");
  const status = document.getElementById("add-friend-db-status");
  const input = document.getElementById("add-friend-username-input");
  if (status) status.innerHTML = "";
  if (input) input.value = "";
  if (modal) modal.classList.add("active");
}

async function submitAddFriend() {
  const input = document.getElementById("add-friend-username-input");
  const status = document.getElementById("add-friend-db-status");
  const username = input?.value.trim();

  if (!username) {
    if (status) status.innerHTML = `<span style="color: #ef4444;">Please enter a player username.</span>`;
    return;
  }

  if (status) status.innerHTML = `<span style="color: #38bdf8;">Checking Divine Network database...</span>`;

  try {
    const res = await API.addFriend(username);
    if (res.success) {
      if (status) status.innerHTML = `<span style="color: #22c55e;">${escapeHtml(res.message || 'Friend request sent!')}</span>`;
      showToast(`Request sent to ${username}!`, "success");
      const fData = await API.getFriends();
      AppState.friends = fData.friends || [];
      AppState.incomingRequests = fData.incoming || [];
      AppState.outgoingRequests = fData.outgoing || [];
      renderFriendsView();
      setTimeout(() => closeModal("modal-add-friend"), 1000);
    } else {
      if (status) status.innerHTML = `<span style="color: #ef4444;">${escapeHtml(res.error || 'Player not found in database.')}</span>`;
    }
  } catch (err) {
    if (status) status.innerHTML = `<span style="color: #ef4444;">Database verification failed.</span>`;
  }
}

async function acceptFriendRequestDirect(id, username) {
  try {
    const res = await fetch("/api/social/friends/accept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, username })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Accepted ${username}!`, "success");
      const fData = await API.getFriends();
      AppState.friends = fData.friends || [];
      AppState.incomingRequests = fData.incoming || [];
      AppState.outgoingRequests = fData.outgoing || [];
      renderFriendsView();
      renderQuickFriends();
    }
  } catch (e) {
    showToast("Error accepting request", "error");
  }
}

async function declineFriendRequestDirect(id, username) {
  try {
    const res = await fetch("/api/social/friends/decline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, username })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Request removed", "info");
      const fData = await API.getFriends();
      AppState.incomingRequests = fData.incoming || [];
      AppState.outgoingRequests = fData.outgoing || [];
      renderFriendsView();
    }
  } catch (e) {
    showToast("Error declining request", "error");
  }
}

async function removeFriendDirect(userId) {
  if (!confirm("Remove this player from your friends list?")) return;
  try {
    const res = await API.removeFriend(userId);
    if (res.success) {
      showToast("Friend removed", "info");
      const fData = await API.getFriends();
      AppState.friends = fData.friends || [];
      renderFriendsView();
      renderQuickFriends();
    }
  } catch (e) {
    showToast("Error removing friend", "error");
  }
}

// -----------------------------------------------------------------------------
// DEDICATED SERVERS & IN-APP SERVER WINDOW
// -----------------------------------------------------------------------------
let serverPollTimer = null;

async function refreshDedicatedServers(silent = false) {
  try {
    const srvData = await API.getServerInstances();
    if (srvData && srvData.servers) {
      AppState.servers = srvData.servers;
      renderDedicatedServers();
      if (AppState.currentTab === "friends") {
        renderSharedServersList();
      }
    }
  } catch (e) {
    if (!silent) showToast("Could not refresh servers list.", "error");
  }
}

function renderDedicatedServers() {
  const grid = document.getElementById("servers-cards-grid");
  if (!grid) return;

  const servers = AppState.servers || [];
  if (servers.length === 0) {
    grid.innerHTML = `<div class="card-panel" style="grid-column: 1/-1; text-align: center; padding: 48px; color: #94a3b8;">No dedicated servers deployed. Click '+ Deploy Dedicated Server' to launch one.</div>`;
    return;
  }

  grid.innerHTML = "";
  servers.forEach(s => {
    const card = document.createElement("div");
    card.className = "card-panel";
    const isOnline = s.status === "running";
    const ramText = s.ram_used_mb ? `${s.ram_used_mb} MB / ${s.ram_allocated_mb || 2048} MB` : `${s.ram_allocated_mb || 2048} MB Allocated`;

    card.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 15px; font-weight: 800; color: #ffffff;">${escapeHtml(s.name)}</span>
          <span class="badge-tag loader">${escapeHtml(s.loader || 'Paper').toUpperCase()}</span>
          <span class="badge-tag version">${escapeHtml(s.mc_version || '1.21.4')}</span>
        </div>
        <span class="badge-tag ${isOnline ? 'mods' : ''}" style="${isOnline ? 'background: rgba(34,197,94,0.2); color: #22c55e; border-color: rgba(34,197,94,0.4);' : 'background: rgba(239,68,68,0.15); color: #ef4444; border-color: rgba(239,68,68,0.3);'}">${isOnline ? 'ONLINE' : 'STOPPED'}</span>
      </div>
      <div style="font-size: 12px; color: #94a3b8; font-family: monospace; margin-bottom: 10px; background: rgba(0,0,0,0.3); padding: 6px 10px; border-radius: 6px;">
        ${escapeHtml(s.public_address || 'localhost:' + s.port)}
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 11px; color: #94a3b8; margin-bottom: 12px;">
        <span>Players: <b style="color: #ffffff;">${s.players_count || 0} / ${s.max_players || 20}</b></span>
        <span>RAM: <b style="color: #ffffff;">${ramText}</b></span>
      </div>
      <div style="display: flex; gap: 8px;">
        <button class="btn btn-primary btn-sm" style="flex: 1;" onclick="openDedicatedServerAppWindow('${s.id}', '${escapeHtml(s.name)}')">Control Panel</button>
        <button class="btn btn-secondary btn-sm" onclick="openServerAccessModal('${s.id}', '${escapeHtml(s.name)}')">Access (${(s.access_users || []).length})</button>
      </div>
    `;
    grid.appendChild(card);
  });
}

function openDedicatedServerAppWindow(serverId, serverName) {
  const modal = document.getElementById("modal-server-control-panel-frame");
  const title = document.getElementById("inapp-server-window-title");
  const iframe = document.getElementById("inapp-server-iframe");

  if (title) title.textContent = `Divine Server Panel — ${serverName || serverId}`;
  if (iframe) iframe.src = `/server.html?id=${encodeURIComponent(serverId)}`;
  if (modal) modal.classList.add("active");
}

let currentAccessServerId = null;

async function openServerAccessModal(serverId, name) {
  currentAccessServerId = serverId;
  const title = document.getElementById("server-access-title");
  if (title) title.textContent = `Server Collaborator Access — ${name}`;

  const listEl = document.getElementById("server-access-users-list");
  if (listEl) listEl.innerHTML = `<div style="font-size: 12px; color: #94a3b8;">Loading collaborator permissions...</div>`;

  document.getElementById("modal-server-access")?.classList.add("active");

  try {
    const res = await API.getServerAccess(serverId);
    const users = res.users || [];
    if (listEl) {
      if (users.length === 0) {
        listEl.innerHTML = `<div style="font-size: 12px; color: #94a3b8; padding: 14px; background: rgba(255,255,255,0.03); border-radius: 6px; text-align: center;">No additional Discord collaborators added yet. Add a Discord username, User ID, or Divine name above.</div>`;
      } else {
        listEl.innerHTML = "";
        users.forEach(u => {
          const row = document.createElement("div");
          row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;";
          const perms = u.permissions || ["admin"];
          const permBadges = perms.map(p => `<span style="display:inline-block; padding: 1px 5px; background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.35); color: #38bdf8; border-radius: 3px; font-size: 10px; font-weight: 700; text-transform: uppercase;">${escapeHtml(p)}</span>`).join(" ");
          row.innerHTML = `
            <div style="display: flex; align-items: center; gap: 10px;">
              <img src="https://mc-heads.net/avatar/${encodeURIComponent(u.username)}/28" onerror="this.onerror=null;this.src='/assets/ui_account.png';" style="width: 28px; height: 28px; border-radius: 4px;">
              <div>
                <div style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(u.username)}${u.discord_id ? ` <span style="font-size: 11px; color: #94a3b8; font-weight: 400;">(${escapeHtml(u.discord_id)})</span>` : ''}</div>
                <div style="font-size: 10.5px; color: #94a3b8; margin-top: 3px; display: flex; gap: 4px; flex-wrap: wrap;">${permBadges}</div>
              </div>
            </div>
            <button class="btn btn-secondary btn-sm" style="padding: 4px 10px; color: #ef4444; border-color: rgba(239,68,68,0.3);" onclick="removeServerAccessDirect('${escapeHtml(u.username)}')">Revoke</button>
          `;
          listEl.appendChild(row);
        });
      }
    }
  } catch (e) {
    if (listEl) listEl.innerHTML = `<div style="font-size: 12px; color: #ef4444;">Failed to load access list.</div>`;
  }
}

async function submitGrantServerAccess() {
  const input = document.getElementById("server-access-username-input");
  const username = input?.value.trim();
  if (!username || !currentAccessServerId) {
    showToast("Please enter a Discord username, User ID, or Divine name.", "error");
    input?.focus();
    return;
  }

  const permissions = [];
  if (document.getElementById("server-perm-power")?.checked) permissions.push("power");
  if (document.getElementById("server-perm-console")?.checked) permissions.push("console");
  if (document.getElementById("server-perm-files")?.checked) permissions.push("files");
  if (document.getElementById("server-perm-players")?.checked) permissions.push("players");
  if (document.getElementById("server-perm-settings")?.checked) permissions.push("settings");
  if (document.getElementById("server-perm-network")?.checked) permissions.push("network");

  try {
    const res = await API.addServerSubUser(currentAccessServerId, username, permissions);
    if (res.success) {
      showToast(`Server access granted to ${username}!`, "success");
      if (input) input.value = "";
      openServerAccessModal(currentAccessServerId, "Server");
      refreshDedicatedServers(true);
    } else {
      showToast(res.error || "Failed to grant access.", "error");
    }
  } catch (e) {
    showToast("Error granting server access.", "error");
  }
}

async function removeServerAccessDirect(username) {
  if (!currentAccessServerId || !confirm(`Revoke server access for '${username}'?`)) return;
  try {
    const res = await API.removeServerSubUser(currentAccessServerId, username);
    if (res.success) {
      showToast(`Revoked access for ${username}`, "info");
      openServerAccessModal(currentAccessServerId, "Server");
      refreshDedicatedServers(true);
    }
  } catch (e) {
    showToast("Error revoking access.", "error");
  }
}

// -----------------------------------------------------------------------------
// INSTANCE CREATION
// -----------------------------------------------------------------------------
function openCreateInstanceModal() {
  window.soundEngine?.playClick?.();
  const modal = document.getElementById("modal-create-instance");
  if (modal) {
    const nameInput = document.getElementById("create-instance-name");
    if (nameInput) nameInput.value = "";
    const loaderSel = document.getElementById("create-instance-loader");
    if (loaderSel) loaderSel.value = "fabric";
    const verSel = document.getElementById("create-instance-version");
    if (verSel) verSel.value = "1.21.4";
    const ramSlider = document.getElementById("create-instance-ram-slider");
    if (ramSlider) ramSlider.value = 4096;
    const ramVal = document.getElementById("create-instance-ram-val");
    if (ramVal) ramVal.textContent = "4096 MB";
    const optToggle = document.getElementById("create-instance-opt-toggle");
    if (optToggle) optToggle.checked = true;
    handleCreateInstanceLoaderChange("fabric");
    modal.classList.add("active");
  }
}

function handleCreateInstanceLoaderChange(loader) {
  const optRow = document.getElementById("create-instance-opt-row");
  if (optRow) {
    optRow.style.display = loader === "fabric" ? "flex" : "none";
  }
}

async function submitCreateInstance() {
  window.soundEngine?.playClick?.();
  const nameInput = document.getElementById("create-instance-name");
  const loaderSel = document.getElementById("create-instance-loader");
  const verSel = document.getElementById("create-instance-version");
  const ramSlider = document.getElementById("create-instance-ram-slider");
  const iconSel = document.getElementById("create-instance-icon");
  const optToggle = document.getElementById("create-instance-opt-toggle");

  const loader = loaderSel?.value || "fabric";
  const mc_version = verSel?.value || "1.21.4";
  let name = nameInput?.value?.trim();
  if (!name) {
    const loaderName = loader.charAt(0).toUpperCase() + loader.slice(1);
    name = `${loaderName} ${mc_version}`;
  }
  const ram_mb = parseInt(ramSlider?.value || "4096", 10);
  const icon = iconSel?.value || "lightning";
  const install_optimization_pack = loader === "fabric" ? (optToggle?.checked ?? true) : false;

  closeModal("modal-create-instance");
  showToast(`Creating instance "${name}"...`, "info");

  try {
    const res = await API.createInstance({
      name,
      mc_version,
      loader,
      ram_mb,
      icon,
      install_optimization_pack
    });

    if (res && res.error) {
      showToast(`Failed to create instance: ${res.error}`, "error");
      return;
    }

    showToast(`Instance "${name}" created successfully!`, "success");
    await loadLauncherData();

    // Select the new instance in the slider
    const newIdx = (AppState.instances || []).findIndex(i => i.name === name || (res.instance && i.id === res.instance.id));
    if (newIdx !== -1) {
      AppState.sliderIndex = newIdx;
      AppState.activeInstanceId = AppState.instances[newIdx].id;
      renderHomeSlider("next");
      const editorSelect = document.getElementById("editor-instance-select");
      if (editorSelect) {
        editorSelect.value = AppState.activeInstanceId;
        loadInstanceIntoEditor(AppState.activeInstanceId);
      }
    }
  } catch (err) {
    showToast("Error creating instance: " + err.message, "error");
  }
}

let cachedPaperVersions = null;

function handleServerTemplateSelection(templateId) {
  const nameInput = document.getElementById("create-server-name");
  const loaderSel = document.getElementById("create-server-loader");
  const tmplMap = {
    survival: { name: "Survival SMP", loader: "paper" },
    creative: { name: "Creative World & Plots", loader: "paper" },
    lobby: { name: "Lobby & Minigames Hub", loader: "paper" },
    hardcore: { name: "Hardcore Survival Realm", loader: "paper" },
    fabric: { name: "Fabric Modded Server", loader: "fabric" },
    custom: { name: "Divine Dedicated Server", loader: "paper" },
  };
  const tmpl = tmplMap[templateId] || tmplMap.custom;
  if (nameInput && (!nameInput.value || Object.values(tmplMap).some(t => t.name === nameInput.value))) {
    nameInput.value = tmpl.name;
  }
  if (loaderSel && tmpl.loader) {
    loaderSel.value = tmpl.loader;
  }
}

async function openCreateServerModal() {
  const modal = document.getElementById("modal-create-server");
  const verSelect = document.getElementById("create-server-version");
  const loaderSelect = document.getElementById("create-server-loader");
  const tmplSelect = document.getElementById("create-server-template");
  if (tmplSelect) tmplSelect.value = "survival";
  handleServerTemplateSelection("survival");
  if (modal) modal.classList.add("active");

  if (!cachedPaperVersions) {
    try {
      const res = await API.getPaperVersions();
      if (res && res.versions && res.versions.length > 0) {
        cachedPaperVersions = res.versions;
      }
    } catch (e) {}
  }

  const versions = cachedPaperVersions || [
    "1.21.4", "1.21.3", "1.21.1", "1.21",
    "1.20.6", "1.20.5", "1.20.4", "1.20.2", "1.20.1", "1.20",
    "1.19.4", "1.19.3", "1.19.2", "1.19.1", "1.19",
    "1.18.2", "1.18.1", "1.18",
    "1.17.1", "1.17",
    "1.16.5", "1.16.4", "1.16.3", "1.16.2", "1.16.1",
    "1.15.2", "1.14.4", "1.13.2", "1.12.2", "1.8.8"
  ];

  if (verSelect) {
    verSelect.innerHTML = versions.map(v => `<option value="${v}" ${v === '1.21.4' ? 'selected' : ''}>Paper ${v}</option>`).join("");
  }
}

async function submitCreateServer() {
  const tmplId = document.getElementById("create-server-template")?.value || "custom";
  const name = document.getElementById("create-server-name")?.value.trim() || "Divine Server";
  const loader = document.getElementById("create-server-loader")?.value || "paper";
  const version = document.getElementById("create-server-version")?.value || "1.21.4";

  showToast(`Deploying ${name} dedicated server...`, "info");
  closeModal("modal-create-server");

  try {
    const res = await API.createServerInstance({
      name,
      loader,
      mc_version: version,
      template_id: tmplId
    });
    if (res.success) {
      showToast(`Server "${name}" deployed successfully!`, "success");
      await refreshDedicatedServers();
    } else {
      showToast(res.error || "Failed to deploy server.", "error");
    }
  } catch (err) {
    showToast("Error deploying server: " + err.message, "error");
  }
}
  AppState.servers.unshift({
    id: tempId,
    name: name,
    loader: loader,
    mc_version: version,
    status: "deploying",
    public_address: "localhost:25565",
    port: 25565,
    players_count: 0
  });
  renderDedicatedServers();

  try {
    const res = await API.createServer({ name, loader, mc_version: version });
    if (res.success) {
      showToast(`Server '${name}' deployed successfully!`, "success");
      await refreshDedicatedServers(true);
    } else {
      showToast(res.error || "Failed to deploy server.", "error");
      await refreshDedicatedServers(true);
    }
  } catch (e) {
    showToast("Error deploying server", "error");
    await refreshDedicatedServers(true);
  }
}

// -----------------------------------------------------------------------------
// SETTINGS & JVM PREFERENCES (COMPREHENSIVE TABS)
// -----------------------------------------------------------------------------
function switchSettingsTab(tabName, element) {
  window.soundEngine?.playClick?.();
  document.querySelectorAll(".settings-tab-item").forEach(t => t.classList.remove("active"));
  element.classList.add("active");

  document.querySelectorAll(".settings-pane").forEach(p => p.style.display = "none");
  const target = document.getElementById(`settings-pane-${tabName}`);
  if (target) target.style.display = "flex";
}

function openSettingsModal() {
  document.getElementById("modal-settings")?.classList.add("active");
  loadSettingsDefaults();
  loadStorageDirectorySettings();
}

function updateSettingsRamDisplay(val) {
  const display = document.getElementById("modal-global-ram-display");
  if (display) display.textContent = `${val} MB`;
}

function setJvmPreset(preset) {
  const input = document.getElementById("modal-jvm-args-input");
  if (!input) return;

  if (preset === "aikar") {
    input.value = "-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch";
    showToast("Applied Aikar's High-Performance Flags", "info");
  } else if (preset === "shenandoah") {
    input.value = "-XX:+UseShenandoahGC -XX:ShenandoahGCHeuristics=compact -XX:+AlwaysPreTouch";
    showToast("Applied Shenandoah Low-Latency GC", "info");
  } else if (preset === "zgc") {
    input.value = "-XX:+UseZGC -XX:+ZGenerational -XX:+AlwaysPreTouch";
    showToast("Applied Generational ZGC", "info");
  }
}

function applyTheme(themeName, showFeedback = false) {
  if (!themeName) themeName = "divine";
  document.documentElement.setAttribute("data-theme", themeName);
  localStorage.setItem("divine_theme", themeName);
  const select = document.getElementById("settings-theme-select");
  if (select && select.value !== themeName) {
    select.value = themeName;
  }
  API.saveSettings({ theme: themeName }).catch(() => {});
  if (showFeedback) {
    window.soundEngine?.playClick?.();
    const names = {
      "divine": "Obsidian & Pure White",
      "all-black": "AMOLED Void (Pure Black)",
      "cyber-cyan": "Cyber Neon Cyan",
      "emerald": "Emerald Matrix",
      "nebula-purple": "Nebula Violet",
      "crimson": "Crimson Red"
    };
    showToast(`Theme switched to ${names[themeName] || themeName}`, "info");
  }
}

function toggleTreeBackground(enabled) {
  const homeHero = document.querySelector(".home-hero-container");
  if (homeHero) {
    if (enabled) {
      homeHero.style.backgroundImage = "linear-gradient(135deg, rgba(9, 10, 15, 0.84) 0%, rgba(9, 10, 15, 0.65) 45%, rgba(9, 10, 15, 0.9) 100%), url('/assets/minecraft_tree_shaders.png')";
    } else {
      homeHero.style.backgroundImage = "none";
    }
  }
}

async function loadSettingsDefaults() {
  try {
    const cfg = await API.getSettings();
    const ramSlider = document.getElementById("modal-global-ram-slider");
    const ramDisp = document.getElementById("modal-global-ram-display");
    const javaInput = document.getElementById("modal-java-path-input");
    const jvmInput = document.getElementById("modal-jvm-args-input");

    if (cfg) {
      if (ramSlider && cfg.ram_mb) ramSlider.value = cfg.ram_mb;
      if (ramDisp && cfg.ram_mb) ramDisp.textContent = `${cfg.ram_mb} MB`;
      if (javaInput && cfg.custom_java_path) javaInput.value = cfg.custom_java_path;
      if (jvmInput && cfg.jvm_args) jvmInput.value = cfg.jvm_args;
      if (cfg.theme) applyTheme(cfg.theme, false);
    }

    // Load storage directories
    loadStorageDirectorySettings();
  } catch (e) {}
}

async function loadStorageDirectorySettings() {
  try {
    const loc = await API.getStorageLocations();
    const gamedirInput = document.getElementById("settings-gamedir-input");
    const instdirInput = document.getElementById("settings-instancesdir-input");
    const badge = document.getElementById("settings-gamedir-type-badge");

    if (loc && gamedirInput) {
      gamedirInput.value = loc.game_dir || "";
      if (instdirInput) {
        instdirInput.value = loc.is_default_instances_dir ? "" : (loc.instances_dir || "");
      }
      if (badge) {
        badge.textContent = loc.is_default_game_dir ? "DEFAULT LOCATION" : "CUSTOM DRIVE LOCATION";
        badge.style.color = loc.is_default_game_dir ? "#94a3b8" : "#38bdf8";
      }
    }
  } catch (e) {}
}

async function applyStorageDirectorySettings() {
  window.soundEngine?.playClick?.();
  const gamedirInput = document.getElementById("settings-gamedir-input");
  const instdirInput = document.getElementById("settings-instancesdir-input");
  const moveFiles = document.getElementById("settings-move-files-checkbox")?.checked !== false;

  const newGameDir = gamedirInput?.value?.trim();
  const newInstDir = instdirInput?.value?.trim() || null;

  if (!newGameDir) {
    showToast("Game directory cannot be empty.", "error");
    return;
  }

  showToast("Updating game directory location...", "info");

  try {
    const res = await API.setStorageLocations(newGameDir, newInstDir, moveFiles);
    if (res.success) {
      showToast(`Game directory set to: ${res.game_dir}`, "success");
      loadStorageDirectorySettings();
      fetchAndRenderInstances();
    } else {
      showToast(res.error || "Failed to update directory", "error");
    }
  } catch (e) {
    showToast("Failed to change directory: " + e.message, "error");
  }
}

function browseGameDirectory() {
  window.soundEngine?.playClick?.();
  const current = document.getElementById("settings-gamedir-input")?.value || "";
  const newPath = prompt("Enter or paste the new folder path for Divine Client on your disk (e.g. D:\\Games\\DivineClient or /home/user/.minecraft):", current);
  if (newPath && newPath.trim()) {
    document.getElementById("settings-gamedir-input").value = newPath.trim();
    showToast("Path entered. Click 'Apply & Save Directory Changes' to confirm.", "info");
  }
}

function browseInstancesDirectory() {
  window.soundEngine?.playClick?.();
  const current = document.getElementById("settings-instancesdir-input")?.value || "";
  const newPath = prompt("Enter or paste custom folder path for Instances & Saves (or leave empty for default):", current);
  if (newPath !== null) {
    document.getElementById("settings-instancesdir-input").value = newPath.trim();
  }
}

async function resetGameDirectoryToDefault() {
  window.soundEngine?.playClick?.();
  try {
    const loc = await API.getStorageLocations();
    if (loc && loc.data_dir) {
      document.getElementById("settings-gamedir-input").value = loc.data_dir;
      showToast("Reset to default location. Click 'Apply & Save Directory Changes' to confirm.", "info");
    }
  } catch (e) {}
}

function resetInstancesDirectoryToDefault() {
  window.soundEngine?.playClick?.();
  const input = document.getElementById("settings-instancesdir-input");
  if (input) {
    input.value = "";
    showToast("Instances will follow the main Game Directory.", "info");
  }
}

function openLauncherStorageFolder() {
  const current = document.getElementById("settings-gamedir-input")?.value || null;
  API.openStorageFolder(current);
}

function openInstancesStorageFolder() {
  const current = document.getElementById("settings-instancesdir-input")?.value || null;
  API.openStorageFolder(current);
}

async function saveGlobalSettings() {
  const ram = parseInt(document.getElementById("modal-global-ram-slider")?.value || 4096);
  const javaPath = document.getElementById("modal-java-path-input")?.value.trim();
  const jvmArgs = document.getElementById("modal-jvm-args-input")?.value.trim();
  const fullscreen = document.getElementById("settings-fullscreen-toggle")?.checked;
  const treeBg = document.getElementById("settings-tree-bg-toggle")?.checked;
  const theme = document.getElementById("settings-theme-select")?.value || "divine";

  applyTheme(theme, false);
  toggleTreeBackground(treeBg);

  try {
    await API.saveSettings({
      ram_mb: ram,
      custom_java_path: javaPath,
      jvm_args: jvmArgs,
      fullscreen: fullscreen,
      theme: theme
    });
    showToast("Settings saved!", "success");
    closeModal("modal-settings");
  } catch (e) {
    showToast("Error saving settings", "error");
  }
}

// -----------------------------------------------------------------------------
// DISCORD GATEWAY, AUTHENTICATION & PROFILE
// -----------------------------------------------------------------------------
let discordAuthPollTimer = null;
let discordLinkPollTimer = null;

async function renderDiscordView() {
  const unlinkedPane = document.getElementById("discord-view-unlinked");
  const linkedPane = document.getElementById("discord-view-linked");

  if (!AppState.discordLinked) {
    if (unlinkedPane) unlinkedPane.style.display = "flex";
    if (linkedPane) linkedPane.style.display = "none";
    startDiscordAuthSession();
  } else {
    if (unlinkedPane) unlinkedPane.style.display = "none";
    if (linkedPane) linkedPane.style.display = "flex";

    const profile = AppState.discordProfile || {};
    const unameEl = document.getElementById("discord-linked-username");
    const idEl = document.getElementById("discord-linked-id");
    const avatarEl = document.getElementById("discord-linked-avatar");
    const timeEl = document.getElementById("discord-linked-time");

    if (unameEl) unameEl.textContent = profile.username || "DiscordUser";
    if (idEl) idEl.textContent = `ID: ${profile.id || "Verified"}`;
    if (avatarEl && profile.avatar_url) avatarEl.src = profile.avatar_url;
    if (timeEl) {
      if (profile.linked_at) {
        timeEl.textContent = new Date(profile.linked_at * 1000).toLocaleDateString();
      } else {
        timeEl.textContent = "Active Session";
      }
    }
  }
}

async function checkLocalDiscordAutoLink() {
  try {
    const det = await API.detectLocalDiscord();
    if (det && det.running) {
      const statusEl = document.getElementById("discord-auth-code-status");
      if (statusEl) statusEl.innerHTML = `<span class="pulse-dot" style="background:#22c55e;"></span> Discord Desktop Detected! Auto-linking...`;
      
      const linkRes = await API.autoLinkLocalDiscord();
      if (linkRes && linkRes.success && linkRes.profile) {
        AppState.discordLinked = true;
        AppState.discordProfile = linkRes.profile;
        
        const [accRes, friendsRes] = await Promise.allSettled([
          API.getAccounts(),
          API.getFriends()
        ]);
        if (accRes.status === "fulfilled" && accRes.value) {
          AppState.accounts = accRes.value.accounts || [];
          AppState.activeAccountId = accRes.value.active_id || (AppState.accounts.length > 0 ? AppState.accounts[0].id : null);
        }
        if (friendsRes.status === "fulfilled" && friendsRes.value) {
          AppState.friends = friendsRes.value.friends || [];
          AppState.incomingRequests = friendsRes.value.incoming || [];
          AppState.outgoingRequests = friendsRes.value.outgoing || [];
        }

        renderTopbar();
        updateNavigationLockState();
        showToast("Discord Desktop detected! Automatically connected to Divine Client.", "success");
        switchTab("overview");
        return true;
      }
    }
  } catch (e) {}
  return false;
}

async function startDiscordAuthSession() {
  const codeEl = document.getElementById("discord-auth-code-display");
  const statusEl = document.getElementById("discord-auth-code-status");

  // Auto-detect local Discord Desktop client
  const autoLinked = await checkLocalDiscordAutoLink();
  if (autoLinked) return;

  if (AppState.discordAuthCode) {
    if (codeEl) codeEl.textContent = AppState.discordAuthCode;
    return;
  }

  if (codeEl) codeEl.textContent = "FETCHING...";
  if (statusEl) statusEl.innerHTML = `<span class="pulse-dot"></span> Generating device link code...`;

  try {
    const res = await API.startSocialLink();
    if (res.code) {
      AppState.discordAuthCode = res.code;
      AppState.discordVerificationUrl = res.verification_url || `https://divineclient.wispbyte.org/link?code=${res.code}`;

      if (codeEl) codeEl.textContent = res.code;
      const botCmdEl = document.getElementById("launcher-bot-cmd");
      if (botCmdEl) botCmdEl.textContent = "/link code:" + res.code;
      if (statusEl) statusEl.innerHTML = `<span class="pulse-dot"></span> Ready. Click 'Authorize with Discord via Website' below.`;

      clearInterval(discordAuthPollTimer);
      discordAuthPollTimer = setInterval(async () => {
        try {
          const poll = await API.pollSocialLink(res.link_id);
          if (poll.status === "linked" && poll.profile) {
            clearInterval(discordAuthPollTimer);
            AppState.discordLinked = true;
            AppState.discordProfile = poll.profile;
            
            const [accRes, friendsRes] = await Promise.allSettled([
              API.getAccounts(),
              API.getFriends()
            ]);
            if (accRes.status === "fulfilled" && accRes.value) {
              AppState.accounts = accRes.value.accounts || [];
              AppState.activeAccountId = accRes.value.active_id || (AppState.accounts.length > 0 ? AppState.accounts[0].id : null);
            }
            if (friendsRes.status === "fulfilled" && friendsRes.value) {
              AppState.friends = friendsRes.value.friends || [];
              AppState.incomingRequests = friendsRes.value.incoming || [];
              AppState.outgoingRequests = friendsRes.value.outgoing || [];
            }

            renderTopbar();
            updateNavigationLockState();
            showToast(`Discord connected! Welcome ${poll.profile.username || "Player"}`, "success");
            switchTab("overview");
          }
        } catch (e) {}
      }, 2000);
    }
  } catch (e) {
    if (codeEl) codeEl.textContent = "DIVINE-AUTH";
    if (statusEl) statusEl.textContent = "Ready for website authorization.";
  }
}


function copyLauncherBotCmd() {
  const code = AppState.discordAuthCode || document.getElementById("discord-auth-code-display")?.textContent || "DIVINE";
  const cmd = "/link code:" + code;
  navigator.clipboard?.writeText?.(cmd);
  showToast("Bot command copied: " + cmd, "info");
}
function copyDiscordAuthCode() {
  const code = document.getElementById("discord-auth-code-display")?.textContent;
  if (code && code !== "DIVINE-WAIT" && code !== "FETCHING...") {
    navigator.clipboard?.writeText?.(code);
    showToast("Discord link code copied!", "info");
  }
}

function openDiscordAuthPage() {
  window.soundEngine?.playClick?.();
  const code = AppState.discordAuthCode || "";
  const statusEl = document.getElementById("discord-auth-code-status");
  if (statusEl) statusEl.innerHTML = `<span class="pulse-dot"></span> Waiting for Discord permission authorization...`;

  // Direct target to /link?code= or /discord/start?code=
  const targetUrl = code ? `https://divineclient.wispbyte.org/link?code=${encodeURIComponent(code)}` : "https://divineclient.wispbyte.org/link";
  
  // Open in browser to trigger the Discord permission prompt
  window.open(targetUrl, "_blank");
  showToast("Opened Discord permission authorization page in your browser.", "info");
}

async function submitDiscordQuickAuth() {
  const input = document.getElementById("discord-quick-username-input");
  const idInput = document.getElementById("discord-quick-id-input");
  const username = input?.value?.trim();
  const discordId = idInput?.value?.trim() || "";

  if (!username) {
    showToast("Please enter a Discord username or tag.", "error");
    input?.focus();
    return;
  }

  const btn = document.getElementById("discord-quick-submit-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Authenticating...";
  }

  try {
    const res = await API.quickDiscordAuth(username, discordId);
    if (res.success && res.linked) {
      AppState.discordLinked = true;
      AppState.discordProfile = res.profile || { username };
      clearInterval(discordAuthPollTimer);

      // Refresh accounts and friends
      const [accRes, friendsRes] = await Promise.allSettled([
        API.getAccounts(),
        API.getFriends()
      ]);
      if (accRes.status === "fulfilled" && accRes.value) {
        AppState.accounts = accRes.value.accounts || [];
        AppState.activeAccountId = accRes.value.active_id || (AppState.accounts.length > 0 ? AppState.accounts[0].id : null);
      }
      if (friendsRes.status === "fulfilled" && friendsRes.value) {
        AppState.friends = friendsRes.value.friends || [];
        AppState.incomingRequests = friendsRes.value.incoming || [];
        AppState.outgoingRequests = friendsRes.value.outgoing || [];
      }

      renderTopbar();
      updateNavigationLockState();
      showToast(`Discord authenticated as ${username}! Welcome to Divine Client.`, "success");
      switchTab("overview");
    } else {
      showToast(res.error || "Failed to authenticate with Discord.", "error");
    }
  } catch (err) {
    showToast("Authentication error. Please try again.", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Sign In with Discord";
    }
  }
}

async function disconnectDiscordAccount() {
  if (!confirm("Are you sure you want to disconnect your Discord account? You will need to sign in again to use Divine Client.")) return;

  try {
    await API.unlinkSocialLink();
    AppState.discordLinked = false;
    AppState.discordProfile = {};
    AppState.discordAuthCode = "";
    clearInterval(discordAuthPollTimer);

    updateNavigationLockState();
    renderTopbar();
    switchTab("discord");
    showToast("Discord account disconnected.", "info");
  } catch (e) {
    showToast("Error disconnecting account.", "error");
  }
}

async function syncDiscordFriendsDirect() {
  try {
    const res = await API.syncDiscordFriends();
    if (res.success) {
      showToast(`Synchronized ${res.synced_count || 0} mutual Discord friends!`, "success");
      const friendsRes = await API.getFriends();
      if (friendsRes) {
        AppState.friends = friendsRes.friends || [];
        AppState.incomingRequests = friendsRes.incoming || [];
        AppState.outgoingRequests = friendsRes.outgoing || [];
        renderQuickFriends();
      }
    } else {
      showToast(res.error || "No new mutual friends found.", "info");
    }
  } catch (e) {
    showToast("Could not sync Discord friends.", "error");
  }
}

async function openDiscordLinkModal() {
  switchTab("discord");
}

function copyDiscordLinkCode() {
  copyDiscordAuthCode();
}

function openDiscordLinkPage() {
  openDiscordAuthPage();
}

// -----------------------------------------------------------------------------
// OFFLINE & MICROSOFT PROFILES
// -----------------------------------------------------------------------------
function openAddAccountModal() {
  toggleAccountDrawer(false);
  document.getElementById("modal-add-account")?.classList.add("active");
}

async function submitAddOfflineAccount() {
  const input = document.getElementById("add-offline-username");
  const username = input?.value.trim();
  if (!username) return;

  try {
    const res = await API.addOfflineAccount(username);
    if (res.success && res.account) {
      await API.setActiveAccount(res.account.id);
      const accData = await API.getAccounts();
      AppState.accounts = accData.accounts || [];
      AppState.activeAccountId = res.account.id;
      renderTopbar();
      closeModal("modal-add-account");
      showToast(`Switched to profile: ${username}`, "success");
    }
  } catch (e) {
    showToast("Error adding profile", "error");
  }
}

let msPollInterval = null;
async function openMicrosoftAuthModal() {
  toggleAccountDrawer(false);
  const modal = document.getElementById("modal-microsoft-auth");
  const codeEl = document.getElementById("ms-auth-code");
  const statusEl = document.getElementById("ms-auth-status");
  if (modal) modal.classList.add("active");

  try {
    const res = await API.startMicrosoftLogin();
    if (res.user_code) {
      if (codeEl) codeEl.textContent = res.user_code;
      if (statusEl) statusEl.textContent = "Enter code at microsoft.com/link to approve.";

      clearInterval(msPollInterval);
      msPollInterval = setInterval(async () => {
        try {
          const poll = await API.pollMicrosoftLogin(res.device_code, 3, 300);
          if (poll.status === "complete" && poll.account) {
            clearInterval(msPollInterval);
            await API.setActiveAccount(poll.account.id);
            const accData = await API.getAccounts();
            AppState.accounts = accData.accounts || [];
            AppState.activeAccountId = poll.account.id;
            renderTopbar();
            closeModal("modal-microsoft-auth");
            showToast(`Signed in as ${poll.account.name}!`, "success");
          }
        } catch (e) {}
      }, 3000);
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = "Error contacting Microsoft.";
  }
}

function closeMicrosoftAuthModal() {
  clearInterval(msPollInterval);
  closeModal("modal-microsoft-auth");
}

function copyMicrosoftAuthCode() {
  const code = document.getElementById("ms-auth-code")?.textContent;
  if (code && code !== "------") {
    navigator.clipboard?.writeText?.(code);
    showToast("Code copied!", "info");
  }
}

function openMicrosoftLinkBrowser() {
  window.open("https://www.microsoft.com/link", "_blank");
}

function openLauncherRedeemModal() {
  document.getElementById("modal-launcher-redeem")?.classList.add("active");
}

function openLauncherRedeemModal() {
  document.getElementById("modal-launcher-redeem")?.classList.add("active");
}

function openCosmeticRedeemModal() {
  document.getElementById("modal-launcher-redeem")?.classList.add("active");
}

async function submitCosmeticRedeemFromModal() {
  const input = document.getElementById("launcher-redeem-input");
  const code = input?.value.trim().toUpperCase();
  if (!code) {
    showToast("Please enter a promo code", "error");
    return;
  }

  try {
    const res = await API.redeemPromoCode(code);
    if (res.success) {
      window.soundEngine?.playSuccess?.();
      showToast(`Unlocked: ${res.title}!`, "success");
      closeModal("modal-launcher-redeem");
      loadCosmeticsWardrobe();
      if (input) input.value = "";
    } else {
      showToast(res.error || "Failed to redeem code", "error");
    }
  } catch (err) {
    showToast("Error redeeming promo code", "error");
  }
}

async function submitQuickRedeemCode() {
  const input = document.getElementById("cosmetics-quick-code-input");
  const code = input?.value.trim().toUpperCase();
  if (!code) {
    showToast("Please enter a promo code", "error");
    return;
  }

  try {
    const res = await API.redeemPromoCode(code);
    if (res.success) {
      window.soundEngine?.playSuccess?.();
      showToast(`Unlocked: ${res.title}!`, "success");
      loadCosmeticsWardrobe();
      if (input) input.value = "";
    } else {
      showToast(res.error || "Failed to redeem code", "error");
    }
  } catch (err) {
    showToast("Error redeeming code", "error");
  }
}

async function submitLauncherRedeemCode() {
  const input = document.getElementById("launcher-redeem-input");
  const code = input?.value.trim();
  if (!code) return;

  // Try promo codes first
  try {
    const promoRes = await API.redeemPromoCode(code);
    if (promoRes.success) {
      window.soundEngine?.playSuccess?.();
      showToast(`Unlocked: ${promoRes.title}!`, "success");
      closeModal("modal-launcher-redeem");
      loadCosmeticsWardrobe();
      return;
    }
  } catch (e) {}

  try {
    const res = await API.redeemServerCode(code);
    if (res.success) {
      showToast("Key redeemed successfully!", "success");
      closeModal("modal-launcher-redeem");
    } else {
      showToast(res.error || "Invalid key", "error");
    }
  } catch (e) {
    showToast("Error redeeming key", "error");
  }
}

// -----------------------------------------------------------------------------
// IN-GAME CLIENT MOD MENU CONTROLLER (IMAGE-1 STYLE)
// -----------------------------------------------------------------------------

const MOD_ICONS_SVG = {
  speed: `<svg viewBox="0 0 24 24"><path d="M12 4a8 8 0 0 0-8 8c0 2.2 1 4.2 2.6 5.6L12 12l4 4.5c1.4-1.3 2.4-3.1 2.4-4.5a8 8 0 0 0-8-8z"/><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"/></svg>`,
  navigation: `<svg viewBox="0 0 24 24"><path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z"/></svg>`,
  search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
  brightness: `<svg viewBox="0 0 24 24"><path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1z"/></svg>`,
  clock: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
  masks: `<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 0 0-10 10c0 5.52 4.48 10 10 10s10-4.48 10-10A10 10 0 0 0 12 2zm-3 8a2 2 0 1 1 0-4 2 2 0 0 1 0 4zm6 0a2 2 0 1 1 0-4 2 2 0 0 1 0 4zm-7.9 6c.9-2.3 3.1-4 5.9-4s5 1.7 5.9 4H7.1z"/></svg>`,
  particles: `<svg viewBox="0 0 24 24"><path d="M12 2l2.4 7.2L22 10l-6 4.8 2.3 7.2-6.3-4.6-6.3 4.6 2.3-7.2L2 10l7.6-.8z"/></svg>`,
  shield: `<svg viewBox="0 0 24 24"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/></svg>`,
  keyboard: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M6 12h.01M10 12h.01M14 12h.01M18 12h.01M8 16h8"/></svg>`,
  shield_half: `<svg viewBox="0 0 24 24"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12V1z"/></svg>`,
  flask: `<svg viewBox="0 0 24 24"><path d="M6 22h12a2 2 0 0 0 2-2c0-.5-.2-1-.5-1.4L15 11.2V4h1a1 1 0 0 0 0-2H8a1 1 0 0 0 0 2h1v7.2L4.5 18.6A2 2 0 0 0 4 20a2 2 0 0 0 2 2z"/></svg>`,
  crosshair: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="22" y1="12" x2="18" y2="12"/><line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/><line x1="12" y1="22" x2="12" y2="18"/><circle cx="12" cy="12" r="2"/></svg>`,
  run: `<svg viewBox="0 0 24 24"><path d="M13.5 5.5a2 2 0 1 0-2-2 2 2 0 0 0 2 2zM9.8 8.9L7 23l2.1.4 2.2-11.2 3.1 3.1V23h2.2v-8.8l-3.3-3.3 1-5.1C15.8 7.3 18.1 8 20 8V5.8c-1.5 0-3.3-.6-4.5-1.8l-1.4-1.4C13.7 2.2 13.1 2 12.5 2c-.6 0-1.2.2-1.6.6L7 6.5v4.7h2.2V8.9z"/></svg>`,
  wifi: `<svg viewBox="0 0 24 24"><path d="M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01"/></svg>`,
  blur: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="8"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/></svg>`,
  sun: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`,
  target: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>`,
  sword: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 17.5L3 6V3h3l11.5 11.5M13 19l2 2 6-6-2-2M19 13l2 2"/></svg>`,
  eye: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,
  cube: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>`,
  list: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>`,
  box: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>`,
  alert: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
  chat: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
  cpu: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>`,
  counter: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/></svg>`,
  badge: `<svg viewBox="0 0 256 256"><g fill="#ffffff"><g transform="rotate(0 128 128)"><path d="M128,14 C144,40 146,72 134,94 Q128,98 124,92 C120,70 122,38 128,14 Z"/></g><g transform="rotate(45 128 128)"><path d="M128,14 C144,40 146,72 134,94 Q128,98 124,92 C120,70 122,38 128,14 Z"/></g><g transform="rotate(90 128 128)"><path d="M128,14 C144,40 146,72 134,94 Q128,98 124,92 C120,70 122,38 128,14 Z"/></g><g transform="rotate(135 128 128)"><path d="M128,14 C144,40 146,72 134,94 Q128,98 124,92 C120,70 122,38 128,14 Z"/></g><g transform="rotate(180 128 128)"><path d="M128,14 C144,40 146,72 134,94 Q128,98 124,92 C120,70 122,38 128,14 Z"/></g><g transform="rotate(225 128 128)"><path d="M128,14 C144,40 146,72 134,94 Q128,98 124,92 C120,70 122,38 128,14 Z"/></g><g transform="rotate(270 128 128)"><path d="M128,14 C144,40 146,72 134,94 Q128,98 124,92 C120,70 122,38 128,14 Z"/></g><g transform="rotate(315 128 128)"><path d="M128,14 C144,40 146,72 134,94 Q128,98 124,92 C120,70 122,38 128,14 Z"/></g><circle cx="128" cy="128" r="34"/></g><circle cx="128" cy="128" r="58" fill="none" stroke="#ffffff" stroke-width="8"/></svg>`,
  flame: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 23c-4.97 0-9-4.03-9-9 0-3.53 2.06-6.61 5.12-8.08.38-.18.84-.04 1.05.33.22.37.12.84-.22 1.1C7.62 8.44 7 9.89 7 11.5c0 2.48 2.02 4.5 4.5 4.5s4.5-2.02 4.5-4.5c0-1.2-.47-2.31-1.25-3.13-.34-.36-.34-.92 0-1.28.34-.36.9-.36 1.25 0C17.07 8.19 17.7 9.77 17.7 11.5c0 .35-.03.7-.08 1.04C18.67 11.19 21 8.84 21 6c0-.44-.29-.82-.71-.94-.42-.12-.86.07-1.07.45C18.4 6.94 17.27 8 16 8c-.55 0-1-.45-1-1 0-2.36 1.2-4.48 3.09-5.74.37-.25.5-.73.31-1.13-.19-.4-.64-.63-1.08-.53C12.7 1.14 9.17 4.22 8.35 8.47 5.73 9.78 4 12.44 4 15.5 4 19.64 7.36 23 11.5 23h.5z"/></svg>`,
  totem: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a3 3 0 0 0-3 3v1H4v4h2v2H4v4h2v1a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3v-1h2v-4h-2v-2h2V6h-5V5a3 3 0 0 0-3-3zm-1 6h2v2h-2V8zm-4 4h2v2H7v-2zm10 0h-2v2h2v-2zm-6 4h4v2h-4v-2z"/></svg>`
};

let InGameModState = {
  mods: {},
  activeCategory: "all",
  searchQuery: "",
  activeModOptionsId: null,
  cosmetics: null,
  friends: []
};

async function openInGameModMenu(initialTab = "mods") {
  window.soundEngine?.playClick?.();
  const overlay = document.getElementById("ingame-modmenu-overlay");
  if (overlay) {
    overlay.style.display = "flex";
  }

  // Load mods data
  try {
    const res = await API.getIngameMods();
    if (res.success) {
      InGameModState.mods = res.mods || {};
      renderModCards();
    }
  } catch (err) {
    console.error("Failed to load in-game mods:", err);
  }

  // Switch initial subtab if provided
  if (initialTab !== "mods") {
    const btn = Array.from(document.querySelectorAll(".modmenu-nav-btn")).find(b => b.textContent.trim().toLowerCase().includes(initialTab));
    if (btn) switchModMenuTab(initialTab, btn);
  }

  initDraggableHud();
}

function closeInGameModMenu() {
  window.soundEngine?.playClick?.();
  const overlay = document.getElementById("ingame-modmenu-overlay");
  if (overlay) {
    overlay.style.display = "none";
  }
}

// Global hotkeys (ESC to close, Right Shift / M to open mod menu)
document.addEventListener("keydown", (e) => {
  const overlay = document.getElementById("ingame-modmenu-overlay");
  if (overlay && overlay.style.display === "flex") {
    if (e.key === "Escape") {
      closeInGameModMenu();
    }
  }
});

function switchModMenuTab(tabName, btn) {
  window.soundEngine?.playClick?.();
  document.querySelectorAll(".modmenu-nav-btn").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");

  document.querySelectorAll(".modmenu-pane").forEach(p => p.style.display = "none");
  const target = document.getElementById(`modmenu-pane-${tabName}`);
  if (target) {
    target.style.display = (tabName === "mods") ? "block" : "block";
    target.classList.add("active");
  }

  // Toggle filter bar visibility
  const filterBar = document.getElementById("modmenu-filter-bar");
  if (filterBar) {
    filterBar.style.display = (tabName === "mods") ? "flex" : "none";
  }

  if (tabName === "cosmetics") {
    renderInGameCosmeticsTab();
  } else if (tabName === "friends") {
    renderInGameFriendsTab();
  }
}

function filterModCategory(category, pill) {
  window.soundEngine?.playClick?.();
  InGameModState.activeCategory = category;
  document.querySelectorAll(".modmenu-filter-pill").forEach(p => p.classList.remove("active"));
  if (pill) pill.classList.add("active");
  renderModCards();
}

function filterModCards(query) {
  InGameModState.searchQuery = (query || "").toLowerCase().trim();
  renderModCards();
}

function renderModCards() {
  const grid = document.getElementById("modmenu-cards-grid");
  if (!grid) return;

  const mods = InGameModState.mods;
  const cat = InGameModState.activeCategory;
  const q = InGameModState.searchQuery;

  let filtered = Object.values(mods).filter(m => {
    if (cat !== "all" && m.category !== cat) return false;
    if (q && !m.name.toLowerCase().includes(q) && !m.description.toLowerCase().includes(q)) return false;
    return true;
  });

  if (filtered.length === 0) {
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #94a3b8; font-size: 14px;">No mods found matching your search query.</div>`;
    return;
  }

  grid.innerHTML = filtered.map(m => {
    const isEnabled = Boolean(m.enabled);
    const iconSvg = MOD_ICONS_SVG[m.icon] || MOD_ICONS_SVG.shield;
    
    return `
      <div class="modmenu-card" data-mod-id="${escapeHtml(m.id)}">
        <div class="modmenu-card-top">
          <div class="modmenu-card-icon">
            ${iconSvg}
          </div>
          <div class="modmenu-card-title">${escapeHtml(m.name)}</div>
          <div class="modmenu-card-desc">${escapeHtml(m.description)}</div>
        </div>

        <!-- Options Row Button with Gear Icon -->
        <div class="modmenu-card-options-row" onclick="openModOptions('${escapeHtml(m.id)}')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          <span>OPTIONS</span>
        </div>

        <!-- Full-Width Bottom Status Toggle Bar (Green / Red) -->
        <button class="modmenu-status-bar ${isEnabled ? 'enabled' : 'disabled'}" onclick="toggleModDirect('${escapeHtml(m.id)}')">
          ${isEnabled ? 'ENABLED' : 'DISABLED'}
        </button>
      </div>
    `;
  }).join("");
}

async function toggleModDirect(modId) {
  window.soundEngine?.playClick?.();
  const current = InGameModState.mods[modId];
  if (!current) return;

  const newState = !current.enabled;
  current.enabled = newState;
  renderModCards();

  try {
    const res = await API.toggleIngameMod(modId, newState);
    if (res.success && res.mod) {
      InGameModState.mods[modId] = res.mod;
    }
  } catch (err) {
    console.error("Failed to toggle mod:", err);
  }
}

function openModOptions(modId) {
  window.soundEngine?.playClick?.();
  const mod = InGameModState.mods[modId];
  if (!mod) return;

  InGameModState.activeModOptionsId = modId;
  const title = document.getElementById("mod-options-title");
  const body = document.getElementById("mod-options-body");
  if (title) title.textContent = `${mod.name} Settings`;

  const opts = mod.options || {};
  let html = "";

  // Dynamic Options Controls
  if (modId === "fps_display") {
    html = `
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Show Background Box</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-fps-bg" ${opts.background ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Text Shadow</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-fps-shadow" ${opts.font_shadow ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
      <div>
        <label style="font-size: 12px; font-weight: 800; color: #ffffff; display: block; margin-bottom: 6px;">Prefix Text</label>
        <input type="text" class="input-field" id="opt-fps-prefix" value="${escapeHtml(opts.prefix || 'FPS: ')}">
      </div>
    `;
  } else if (modId === "fullbright_gamma") {
    html = `
      <div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
          <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Gamma Brightness Level</label>
          <span style="color: #38bdf8; font-weight: 800;" id="opt-gamma-val">${opts.gamma_boost || 1000}%</span>
        </div>
        <input type="range" class="range-slider" min="100" max="1500" step="50" value="${opts.gamma_boost || 1000}" oninput="document.getElementById('opt-gamma-val').textContent = this.value + '%'" id="opt-gamma-slider">
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Instant Toggle (No Fade)</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-gamma-instant" ${opts.instant_toggle ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
    `;
  } else if (modId === "cinematic_zoom") {
    html = `
      <div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
          <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Zoom Factor</label>
          <span style="color: #38bdf8; font-weight: 800;" id="opt-zoom-val">${opts.zoom_factor || 4.0}x</span>
        </div>
        <input type="range" class="range-slider" min="2" max="10" step="0.5" value="${opts.zoom_factor || 4.0}" oninput="document.getElementById('opt-zoom-val').textContent = this.value + 'x'" id="opt-zoom-slider">
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Smooth Animation</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-zoom-smooth" ${opts.smooth_animation ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Scroll Wheel Zoom In/Out</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-zoom-scroll" ${opts.scroll_zoom ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
    `;
  } else if (modId === "divine_nametags") {
    html = `
      <!-- In-Game Nametag Live Preview (Matching img 2) -->
      <div style="background: url('/assets/minecraft_tree_shaders.png') center/cover; padding: 20px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.2); display: flex; flex-direction: column; align-items: center; justify-content: center; margin-bottom: 8px;">
        <div style="background: rgba(0,0,0,0.75); border: 1px solid rgba(255,255,255,0.25); border-radius: 4px; padding: 4px 10px; display: flex; align-items: center; gap: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.6);">
          <img src="/assets/divine_icon.png" style="width: 15px; height: 15px; object-fit: contain;" alt="Badge">
          <span style="color: #ffffff; font-size: 13px; font-weight: 800; font-family: monospace;">Player</span>
        </div>
        <div style="font-size: 11px; color: #ffffff; margin-top: 8px; font-weight: 700; text-shadow: 0 2px 4px rgba(0,0,0,0.8);">Live In-Game Nametag Preview</div>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Show Badge on Self</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-nametag-self" ${opts.show_on_self !== false ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Show Badge on All Divine Users</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-nametag-all" ${opts.show_on_all_divine_users !== false ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
    `;
  } else if (modId === "low_fire") {
    html = `
      <div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
          <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Fire Screen Overlay Height</label>
          <span style="color: #38bdf8; font-weight: 800;" id="opt-fire-height-val">${opts.fire_height || 30}%</span>
        </div>
        <input type="range" class="range-slider" min="10" max="100" step="5" value="${opts.fire_height || 30}" oninput="document.getElementById('opt-fire-height-val').textContent = this.value + '%'" id="opt-fire-height-slider">
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Transparent Fire Particles</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-fire-transparent" ${opts.transparent_particles !== false ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Blue Soul Fire Theme</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-fire-blue" ${opts.blue_soul_fire ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
    `;
  } else if (modId === "small_totem") {
    html = `
      <div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
          <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Held Totem Item Scale</label>
          <span style="color: #38bdf8; font-weight: 800;" id="opt-totem-scale-val">${opts.totem_scale || 0.5}x</span>
        </div>
        <input type="range" class="range-slider" min="0.3" max="1.0" step="0.05" value="${opts.totem_scale || 0.5}" oninput="document.getElementById('opt-totem-scale-val').textContent = parseFloat(this.value).toFixed(2) + 'x'" id="opt-totem-scale-slider">
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Disable Pop-up Screen Animation</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-totem-disable-popup" ${opts.disable_popup_animation !== false ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Compact Offhand Items</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-totem-compact-offhand" ${opts.compact_offhand !== false ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
    `;
  } else {
    html = `
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <label style="font-size: 13px; font-weight: 800; color: #ffffff;">Enabled in Game</label>
        <label class="toggle-switch"><input type="checkbox" id="opt-generic-enabled" ${mod.enabled ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
      <div>
        <label style="font-size: 12px; font-weight: 800; color: #ffffff; display: block; margin-bottom: 6px;">Keybind / Activation Hotkey</label>
        <input type="text" class="input-field" id="opt-generic-keybind" value="${escapeHtml(opts.keybind || 'None')}">
      </div>
    `;
  }

  if (body) body.innerHTML = html;
  document.getElementById("modal-mod-options")?.classList.add("active");
}

async function saveActiveModOptions() {
  const modId = InGameModState.activeModOptionsId;
  if (!modId || !InGameModState.mods[modId]) return;

  const mod = InGameModState.mods[modId];
  const newOpts = { ...(mod.options || {}) };

  if (modId === "fps_display") {
    newOpts.background = document.getElementById("opt-fps-bg")?.checked;
    newOpts.font_shadow = document.getElementById("opt-fps-shadow")?.checked;
    newOpts.prefix = document.getElementById("opt-fps-prefix")?.value || "FPS: ";
  } else if (modId === "fullbright_gamma") {
    newOpts.gamma_boost = parseInt(document.getElementById("opt-gamma-slider")?.value || "1000", 10);
    newOpts.instant_toggle = document.getElementById("opt-gamma-instant")?.checked;
  } else if (modId === "cinematic_zoom") {
    newOpts.zoom_factor = parseFloat(document.getElementById("opt-zoom-slider")?.value || "4.0");
    newOpts.smooth_animation = document.getElementById("opt-zoom-smooth")?.checked;
    newOpts.scroll_zoom = document.getElementById("opt-zoom-scroll")?.checked;
  } else if (modId === "divine_nametags") {
    newOpts.show_on_self = document.getElementById("opt-nametag-self")?.checked;
    newOpts.show_on_all_divine_users = document.getElementById("opt-nametag-all")?.checked;
  } else if (modId === "low_fire") {
    newOpts.fire_height = parseInt(document.getElementById("opt-fire-height-slider")?.value || "30", 10);
    newOpts.transparent_particles = document.getElementById("opt-fire-transparent")?.checked;
    newOpts.blue_soul_fire = document.getElementById("opt-fire-blue")?.checked;
  } else if (modId === "small_totem") {
    newOpts.totem_scale = parseFloat(document.getElementById("opt-totem-scale-slider")?.value || "0.5");
    newOpts.disable_popup_animation = document.getElementById("opt-totem-disable-popup")?.checked;
    newOpts.compact_offhand = document.getElementById("opt-totem-compact-offhand")?.checked;
  }

  try {
    const res = await API.updateIngameModOptions(modId, newOpts);
    if (res.success && res.mod) {
      InGameModState.mods[modId] = res.mod;
      showToast(`${mod.name} options saved!`, "success");
    }
  } catch (err) {
    showToast("Failed to save mod options", "error");
  }

  closeModal("modal-mod-options");
  renderModCards();
}

// -----------------------------------------------------------------------------
// COSMETICS WARDROBE CONTROLLER (LAUNCHER & IN-GAME)
// -----------------------------------------------------------------------------

async function loadCosmeticsWardrobe() {
  try {
    const res = await API.getCosmetics();
    if (res.success) {
      InGameModState.cosmetics = res;
      renderCosmeticsGrid("all");
      updateWardrobeVisuals();
    }
  } catch (err) {
    console.error("Failed to load cosmetics:", err);
  }
}

function filterCosmeticsCategory(category, btn) {
  window.soundEngine?.playClick?.();
  document.querySelectorAll(".cosmetics-category-pills .pill-btn").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  renderCosmeticsGrid(category);
}

function renderCosmeticsGrid(filterCategory = "all") {
  const grid = document.getElementById("cosmetics-items-grid");
  if (!grid || !InGameModState.cosmetics) return;

  const cats = InGameModState.cosmetics.categories || {};
  let allItems = [];

  if (filterCategory === "all") {
    Object.keys(cats).forEach(cat => {
      cats[cat].forEach(it => allItems.push({ ...it, slotCategory: cat }));
    });
  } else if (cats[filterCategory]) {
    cats[filterCategory].forEach(it => allItems.push({ ...it, slotCategory: filterCategory }));
  }

  // ONLY display unlocked/redeemed items in the cosmetics inventory
  const unlockedItems = allItems.filter(it => Boolean(it.unlocked));

  if (unlockedItems.length === 0) {
    grid.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 48px 20px; background: rgba(15,23,42,0.4); border: 1px dashed rgba(255,255,255,0.15); border-radius: 12px;">
        <div style="width: 48px; height: 48px; margin: 0 auto 12px; border-radius: 50%; background: rgba(255,255,255,0.06); display: flex; align-items: center; justify-content: center;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2"><path d="M20.38 3.46L16 2a4 4 0 01-8 0L3.62 3.46a2 2 0 00-1.34 2.23l.58 3.47a1 1 0 00.99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 002-2V10h2.15a1 1 0 00.99-.84l.58-3.47a2 2 0 00-1.34-2.23z"/></svg>
        </div>
        <div style="font-size: 15px; font-weight: 800; color: #ffffff; margin-bottom: 6px;">No Cosmetics Unlocked</div>
        <div style="font-size: 12.5px; color: #94a3b8; max-width: 380px; margin: 0 auto 16px; line-height: 1.5;">Cosmetics only appear here once redeemed. Enter your promo code (e.g. <b>BOOSTER2026</b>) above to unlock cloaks, wings, and accessories.</div>
      </div>
    `;
    return;
  }

  grid.innerHTML = unlockedItems.map(it => {
    const isEquipped = Boolean(it.equipped);
    const slot = it.slotCategory.endsWith("s") ? it.slotCategory.slice(0, -1) : it.slotCategory;

    return `
      <div class="cosmetic-card-tile ${isEquipped ? 'equipped' : ''}">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
          <span style="font-size: 10px; font-weight: 800; color: #22c55e; background: rgba(34,197,94,0.15); padding: 2px 6px; border-radius: 4px;">
            UNLOCKED
          </span>
          <span style="font-size: 11px; font-weight: 800; color: #94a3b8;">${escapeHtml(it.rarity || 'Rare')}</span>
        </div>

        <div style="font-size: 13.5px; font-weight: 800; color: #ffffff; margin-bottom: 4px;">${escapeHtml(it.name)}</div>
        <p style="font-size: 11px; color: #94a3b8; margin-bottom: 12px; line-height: 1.35;">${escapeHtml(it.description || '')}</p>

        <div style="margin-top: auto;">
          <button class="btn ${isEquipped ? 'btn-secondary' : 'btn-primary'} btn-sm" style="width: 100%; justify-content: center;" onclick="equipCosmeticDirect('${slot}', '${isEquipped ? 'none' : escapeHtml(it.id)}')">
            ${isEquipped ? 'Unequip' : 'Equip'}
          </button>
        </div>
      </div>
    `;
  }).join("");
}

async function equipCosmeticDirect(slot, itemId) {
  window.soundEngine?.playClick?.();
  try {
    const res = await API.equipCosmetic(slot, itemId === 'none' ? null : itemId);
    if (res.success) {
      showToast(itemId === 'none' ? `Unequipped ${slot}` : `Equipped ${slot}!`, "success");
      loadCosmeticsWardrobe();
    }
  } catch (err) {
    showToast(err.message || "Failed to equip cosmetic", "error");
  }
}

function updateWardrobeVisuals() {
  if (!InGameModState.cosmetics) return;
  const eq = InGameModState.cosmetics.equipped || {};

  const cloakName = document.getElementById("equipped-cloak-name") || document.getElementById("equipped-cape-name");
  const wingsName = document.getElementById("equipped-wings-name");
  const haloName = document.getElementById("equipped-halo-name");
  const auraName = document.getElementById("equipped-aura-name");
  const badgeName = document.getElementById("equipped-badge-name");

  const currentCloak = eq.cloak || eq.cape;
  if (cloakName) cloakName.textContent = currentCloak ? currentCloak.replace(/_/g, " ").toUpperCase() : "None";
  if (wingsName) wingsName.textContent = eq.wings ? eq.wings.replace(/_/g, " ").toUpperCase() : "None";
  if (haloName) haloName.textContent = eq.halo ? eq.halo.replace(/_/g, " ").toUpperCase() : "None";
  if (auraName) auraName.textContent = eq.aura ? eq.aura.replace(/_/g, " ").toUpperCase() : "None";
  if (badgeName) badgeName.textContent = eq.badge ? "Divine Pure White Sun" : "None";

  // Visual Graphics updates
  const cloakVis = document.getElementById("wardrobe-cloak-visual") || document.getElementById("wardrobe-cape-visual");
  const wingsVis = document.getElementById("wardrobe-wings-visual");
  const haloVis = document.getElementById("wardrobe-halo-visual");

  if (wingsVis) {
    wingsVis.style.display = eq.wings ? "flex" : "none";
  }
  if (haloVis) {
    haloVis.style.display = eq.halo ? "block" : "none";
  }
}

function renderInGameCosmeticsTab() {
  const container = document.getElementById("modmenu-cosmetics-container");
  if (!container) return;

  container.innerHTML = `
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
      <div>
        <div style="font-size: 15px; font-weight: 900; color: #ffffff;">In-Game Cosmetics Wardrobe</div>
        <div style="font-size: 12px; color: #94a3b8;">Cosmetics are linked to your Divine Launcher account and visible across all multiplayer servers.</div>
      </div>
      <button class="btn btn-primary btn-sm" onclick="openCosmeticRedeemModal()">Redeem Product Code</button>
    </div>
    <div id="ingame-cosmetics-subgrid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px;"></div>
  `;

  // Populate
  loadCosmeticsWardrobe().then(() => {
    const subgrid = document.getElementById("ingame-cosmetics-subgrid");
    if (subgrid && InGameModState.cosmetics) {
      const cats = InGameModState.cosmetics.categories || {};
      let items = [];
      Object.keys(cats).forEach(c => cats[c].forEach(it => items.push({ ...it, slotCategory: c })));
      subgrid.innerHTML = items.map(it => {
        const isUnlocked = Boolean(it.unlocked);
        const isEquipped = Boolean(it.equipped);
        const slot = it.slotCategory.endsWith("s") ? it.slotCategory.slice(0, -1) : it.slotCategory;
        return `
          <div class="cosmetic-card-tile ${isEquipped ? 'equipped' : ''}">
            <div style="font-size: 13px; font-weight: 800; color: #ffffff; margin-bottom: 4px;">${escapeHtml(it.name)}</div>
            <p style="font-size: 11px; color: #94a3b8; margin-bottom: 10px;">${escapeHtml(it.description || '')}</p>
            ${isUnlocked ? `
              <button class="btn ${isEquipped ? 'btn-secondary' : 'btn-primary'} btn-sm" style="width: 100%; justify-content: center;" onclick="equipCosmeticDirect('${slot}', '${isEquipped ? 'none' : escapeHtml(it.id)}')">
                ${isEquipped ? 'Unequip' : 'Equip'}
              </button>
            ` : `
              <button class="btn btn-secondary btn-sm" style="width: 100%; justify-content: center;" onclick="openCosmeticRedeemModal()">
                Redeem Code
              </button>
            `}
          </div>
        `;
      }).join("");
    }
  });
}

// -----------------------------------------------------------------------------
// IN-GAME FRIENDS TAB (SYNCED • NO CLIENT-SIDE ADDING)
// -----------------------------------------------------------------------------

async function renderInGameFriendsTab() {
  const grid = document.getElementById("modmenu-friends-grid");
  if (!grid) return;

  try {
    const res = await API.getIngameFriends();
    const friends = res.friends || [];

    if (friends.length === 0) {
      grid.innerHTML = `
        <div class="card-panel" style="grid-column: 1/-1; text-align: center; padding: 40px; color: #94a3b8;">
          No Divine friends online. Add friends in the Divine Launcher!
        </div>
      `;
      return;
    }

    grid.innerHTML = friends.map(f => {
      const uname = f.username || "Friend";
      const skinUrl = f.avatar_url || `https://minotar.net/helm/${encodeURIComponent(uname)}/36.png`;
      const isOnline = f.online !== false;

      return `
        <div class="card-panel" style="display: flex; align-items: center; justify-content: space-between; padding: 14px 16px;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <img src="${skinUrl}" style="width: 38px; height: 38px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.2);" alt="${escapeHtml(uname)}">
            <div>
              <div style="display: flex; align-items: center; gap: 6px;">
                <!-- Divine Sun Badge next to player name matching img 2 -->
                <img src="/assets/divine_icon.png" style="width: 14px; height: 14px; object-fit: contain;" alt="Divine Icon" title="Verified Divine Client User">
                <span style="font-size: 13.5px; font-weight: 800; color: #ffffff;">${escapeHtml(uname)}</span>
              </div>
              <div style="font-size: 11px; color: ${isOnline ? '#22c55e' : '#94a3b8'};">
                ${escapeHtml(f.presence_detail || (isOnline ? 'Online in Game' : 'Offline'))}
              </div>
            </div>
          </div>

          <div style="display: flex; gap: 6px;">
            <button class="btn btn-secondary btn-sm" onclick="showToast('Party invite sent to ${escapeHtml(uname)}!', 'success')">Invite</button>
            <button class="btn btn-secondary btn-sm" onclick="showToast('Whispering to ${escapeHtml(uname)}...', 'info')">Whisper</button>
          </div>
        </div>
      `;
    }).join("");
  } catch (err) {
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: #ef4444;">Failed to sync friends.</div>`;
  }
}

// -----------------------------------------------------------------------------
// DRAGGABLE HUD EDITOR INITIALIZER
// -----------------------------------------------------------------------------

function initDraggableHud() {
  const items = document.querySelectorAll(".draggable-hud-item");
  items.forEach(el => {
    let isDragging = false;
    let startX, startY, origLeft, origTop;

    el.onmousedown = (e) => {
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      origLeft = el.offsetLeft;
      origTop = el.offsetTop;
      el.style.zIndex = 100;

      document.onmousemove = (moveEvent) => {
        if (!isDragging) return;
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;
        el.style.left = `${origLeft + dx}px`;
        el.style.top = `${origTop + dy}px`;
      };

      document.onmouseup = () => {
        isDragging = false;
        document.onmousemove = null;
        document.onmouseup = null;
        el.style.zIndex = 10;
      };
    };
  });
}

function toggleNametagBadges(enabled) {
  API.updateIngameModOptions("divine_nametags", { show_on_all_divine_users: enabled });
  showToast(enabled ? "Divine nametag badges enabled" : "Divine nametag badges disabled", "info");
}

function closeModal(modalId) {
  document.getElementById(modalId)?.classList.remove("active");
}

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}


// -----------------------------------------------------------------------------
// GAME OUTPUT CONSOLE STREAMING & JAVA REPAIR
// -----------------------------------------------------------------------------
let consoleLogPollTimer = null;

function openGameConsole(instanceId = "") {
  openModal("modal-game-console");
  const iid = instanceId || AppState.activeInstanceId || "";
  const inst = AppState.instances.find(i => i.id === iid);
  const statusEl = document.getElementById("console-instance-status");
  if (statusEl) {
    statusEl.textContent = inst ? `Live Output • ${inst.name}` : "Process Live • Streaming Minecraft logs";
  }
  startConsolePolling(iid);
}

function startConsolePolling(instanceId) {
  clearInterval(consoleLogPollTimer);
  pollConsoleLogs(instanceId);
  consoleLogPollTimer = setInterval(() => {
    pollConsoleLogs(instanceId);
  }, 1000);
}

async function pollConsoleLogs(instanceId) {
  const outputEl = document.getElementById("game-console-output");
  if (!outputEl) return;
  
  try {
    const res = await API.getLaunchLogs(instanceId);
    if (res && res.logs !== undefined) {
      if (res.logs) {
        if (Array.isArray(res.logs)) {
          outputEl.textContent = res.logs.join("");
        } else {
          outputEl.textContent = res.logs;
        }
      } else if (!outputEl.textContent) {
        outputEl.textContent = `[DIVINE CLIENT] Launching process with Java 21 LTS...\n[DIVINE CLIENT] Attached stdout/stderr streaming.\n[INFO] Initializing Minecraft launch arguments...\n`;
      }
      
      const autoscroll = document.getElementById("console-autoscroll-toggle")?.checked;
      if (autoscroll) {
        outputEl.scrollTop = outputEl.scrollHeight;
      }
    }
  } catch (e) {}
}

async function killActiveGame() {
  window.soundEngine?.playClick?.();
  const iid = AppState.activeInstanceId || "";
  try {
    showToast("Terminating game process...", "info");
    const res = await API.killGame(iid);
    if (res && res.success) {
      showToast("Game process forcibly terminated.", "success");
      updatePlayButtonVisuals(false, false);
      const outputEl = document.getElementById("game-console-output");
      if (outputEl) {
        outputEl.textContent += "\n[DIVINE CLIENT] Game process terminated by user.\n";
        outputEl.scrollTop = outputEl.scrollHeight;
      }
    } else {
      showToast(res?.error || "No active game process to kill.", "error");
    }
  } catch (err) {
    showToast("Error killing process: " + err.message, "error");
  }
}

async function stopActiveGame() {
  window.soundEngine?.playClick?.();
  const iid = AppState.activeInstanceId || "";
  try {
    showToast("Stopping game...", "info");
    const res = await API.stopGame(iid);
    if (res && res.success) {
      showToast("Game stopped.", "success");
      updatePlayButtonVisuals(false, false);
    } else {
      showToast(res?.error || "No active process to stop.", "error");
    }
  } catch (err) {
    showToast("Error stopping game: " + err.message, "error");
  }
}

window.killActiveGame = killActiveGame;
window.stopActiveGame = stopActiveGame;

function copyConsoleLogs() {
  const outputEl = document.getElementById("game-console-output");
  if (outputEl && outputEl.textContent) {
    navigator.clipboard?.writeText?.(outputEl.textContent);
    showToast("Game console logs copied to clipboard!", "info");
  }
}

function clearConsoleLogs() {
  const outputEl = document.getElementById("game-console-output");
  if (outputEl) {
    outputEl.textContent = "";
    showToast("Console cleared.", "info");
  }
}

async function triggerFixJava() {
  window.soundEngine?.playClick?.();
  showToast("Scanning Java runtime & repairing native libraries...", "info");
  try {
    const res = await API.fixJavaRuntime();
    if (res.success) {
      const input = document.getElementById("modal-java-path-input");
      if (input && res.java_exe) input.value = res.java_exe;
      showToast(res.message || "Java 21 runtime repaired & verified!", "success");
    } else {
      showToast("Java repair failed: " + (res.error || "Unknown error"), "error");
    }
  } catch (e) {
    showToast("Java repair error: " + e.message, "error");
  }
}
