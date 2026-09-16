package com.divine.client.config;

import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.util.*;
import java.util.logging.Logger;

public class DivineConfig {
    private static final Logger LOGGER = Logger.getLogger("DivineConfig");
    private static final File CONFIG_FILE = new File("config/divineclient.json");

    // Mods enabled states
    public boolean fps_enabled = true;
    public boolean coords_enabled = true;
    public boolean keystrokes_enabled = true;
    public boolean armor_status_enabled = true;
    public boolean potion_status_enabled = true;
    public boolean fullbright_enabled = false;
    public boolean zoom_enabled = true;
    public boolean toggle_sprint_enabled = true;
    public boolean memory_hud_enabled = true;
    public boolean ping_hud_enabled = true;
    public boolean low_fire_enabled = true;
    public boolean small_totem_enabled = true;
    public boolean watermark_enabled = true;
    public boolean compass_enabled = false;

    // Cosmetic cloaks
    public String equipped_cloak = "booster";
    public Set<String> unlocked_cloaks = new HashSet<>(Arrays.asList("booster", "cosmic", "eclipse", "staff"));
    public Set<String> redeemed_codes = new HashSet<>(Arrays.asList("BOOSTER2026"));

    // Server connection status
    public String server_status = "cant connect to server";

    public DivineConfig() {
        load();
    }

    public boolean isModEnabled(String id) {
        if ("fps".equalsIgnoreCase(id)) return fps_enabled;
        if ("coords".equalsIgnoreCase(id)) return coords_enabled;
        if ("keystrokes".equalsIgnoreCase(id)) return keystrokes_enabled;
        if ("armor_status".equalsIgnoreCase(id) || "armor".equalsIgnoreCase(id)) return armor_status_enabled;
        if ("potion_status".equalsIgnoreCase(id) || "potion".equalsIgnoreCase(id)) return potion_status_enabled;
        if ("fullbright".equalsIgnoreCase(id) || "gamma".equalsIgnoreCase(id)) return fullbright_enabled;
        if ("zoom".equalsIgnoreCase(id)) return zoom_enabled;
        if ("toggle_sprint".equalsIgnoreCase(id) || "sprint".equalsIgnoreCase(id)) return toggle_sprint_enabled;
        if ("memory".equalsIgnoreCase(id) || "ram".equalsIgnoreCase(id)) return memory_hud_enabled;
        if ("ping".equalsIgnoreCase(id)) return ping_hud_enabled;
        if ("low_fire".equalsIgnoreCase(id)) return low_fire_enabled;
        if ("small_totem".equalsIgnoreCase(id)) return small_totem_enabled;
        if ("watermark".equalsIgnoreCase(id)) return watermark_enabled;
        if ("compass".equalsIgnoreCase(id)) return compass_enabled;
        return false;
    }

    public void setModEnabled(String id, boolean enabled) {
        if ("fps".equalsIgnoreCase(id)) fps_enabled = enabled;
        else if ("coords".equalsIgnoreCase(id)) coords_enabled = enabled;
        else if ("keystrokes".equalsIgnoreCase(id)) keystrokes_enabled = enabled;
        else if ("armor_status".equalsIgnoreCase(id) || "armor".equalsIgnoreCase(id)) armor_status_enabled = enabled;
        else if ("potion_status".equalsIgnoreCase(id) || "potion".equalsIgnoreCase(id)) potion_status_enabled = enabled;
        else if ("fullbright".equalsIgnoreCase(id) || "gamma".equalsIgnoreCase(id)) fullbright_enabled = enabled;
        else if ("zoom".equalsIgnoreCase(id)) zoom_enabled = enabled;
        else if ("toggle_sprint".equalsIgnoreCase(id) || "sprint".equalsIgnoreCase(id)) toggle_sprint_enabled = enabled;
        else if ("memory".equalsIgnoreCase(id) || "ram".equalsIgnoreCase(id)) memory_hud_enabled = enabled;
        else if ("ping".equalsIgnoreCase(id)) ping_hud_enabled = enabled;
        else if ("low_fire".equalsIgnoreCase(id)) low_fire_enabled = enabled;
        else if ("small_totem".equalsIgnoreCase(id)) small_totem_enabled = enabled;
        else if ("watermark".equalsIgnoreCase(id)) watermark_enabled = enabled;
        else if ("compass".equalsIgnoreCase(id)) compass_enabled = enabled;
        save();
    }

    public boolean toggleMod(String id) {
        boolean curr = isModEnabled(id);
        setModEnabled(id, !curr);
        return !curr;
    }

    public boolean redeemCode(String code) {
        if (code == null) return false;
        String clean = code.trim().toUpperCase();
        if ("BOOSTER2026".equals(clean) || "DIVINE2026".equals(clean) || "COSMIC2026".equals(clean)) {
            redeemed_codes.add(clean);
            unlocked_cloaks.add("booster");
            if ("COSMIC2026".equals(clean)) unlocked_cloaks.add("cosmic");
            equipped_cloak = "booster";
            save();
            return true;
        }
        return false;
    }

    public void load() {
        try {
            if (!CONFIG_FILE.exists()) return;
            StringBuilder sb = new StringBuilder();
            try (FileReader reader = new FileReader(CONFIG_FILE)) {
                char[] buf = new char[1024];
                int read;
                while ((read = reader.read(buf)) > 0) {
                    sb.append(buf, 0, read);
                }
            }
            String content = sb.toString();
            fps_enabled = parseBool(content, "fps_enabled", fps_enabled);
            coords_enabled = parseBool(content, "coords_enabled", coords_enabled);
            keystrokes_enabled = parseBool(content, "keystrokes_enabled", keystrokes_enabled);
            armor_status_enabled = parseBool(content, "armor_status_enabled", armor_status_enabled);
            potion_status_enabled = parseBool(content, "potion_status_enabled", potion_status_enabled);
            fullbright_enabled = parseBool(content, "fullbright_enabled", fullbright_enabled);
            zoom_enabled = parseBool(content, "zoom_enabled", zoom_enabled);
            toggle_sprint_enabled = parseBool(content, "toggle_sprint_enabled", toggle_sprint_enabled);
            memory_hud_enabled = parseBool(content, "memory_hud_enabled", memory_hud_enabled);
            ping_hud_enabled = parseBool(content, "ping_hud_enabled", ping_hud_enabled);
            low_fire_enabled = parseBool(content, "low_fire_enabled", low_fire_enabled);
            small_totem_enabled = parseBool(content, "small_totem_enabled", small_totem_enabled);
            watermark_enabled = parseBool(content, "watermark_enabled", watermark_enabled);
            compass_enabled = parseBool(content, "compass_enabled", compass_enabled);
            String clk = parseString(content, "equipped_cloak");
            if (clk != null && !clk.isEmpty()) equipped_cloak = clk;
        } catch (Exception e) {
            LOGGER.warning("Could not load Divine Client config: " + e.getMessage());
        }
    }

    public void save() {
        try {
            File dir = CONFIG_FILE.getParentFile();
            if (dir != null && !dir.exists()) dir.mkdirs();
            StringBuilder sb = new StringBuilder("{\n");
            sb.append("  \"fps_enabled\": ").append(fps_enabled).append(",\n");
            sb.append("  \"coords_enabled\": ").append(coords_enabled).append(",\n");
            sb.append("  \"keystrokes_enabled\": ").append(keystrokes_enabled).append(",\n");
            sb.append("  \"armor_status_enabled\": ").append(armor_status_enabled).append(",\n");
            sb.append("  \"potion_status_enabled\": ").append(potion_status_enabled).append(",\n");
            sb.append("  \"fullbright_enabled\": ").append(fullbright_enabled).append(",\n");
            sb.append("  \"zoom_enabled\": ").append(zoom_enabled).append(",\n");
            sb.append("  \"toggle_sprint_enabled\": ").append(toggle_sprint_enabled).append(",\n");
            sb.append("  \"memory_hud_enabled\": ").append(memory_hud_enabled).append(",\n");
            sb.append("  \"ping_hud_enabled\": ").append(ping_hud_enabled).append(",\n");
            sb.append("  \"low_fire_enabled\": ").append(low_fire_enabled).append(",\n");
            sb.append("  \"small_totem_enabled\": ").append(small_totem_enabled).append(",\n");
            sb.append("  \"watermark_enabled\": ").append(watermark_enabled).append(",\n");
            sb.append("  \"compass_enabled\": ").append(compass_enabled).append(",\n");
            sb.append("  \"equipped_cloak\": \"").append(equipped_cloak).append("\"\n");
            sb.append("}\n");

            try (FileWriter writer = new FileWriter(CONFIG_FILE)) {
                writer.write(sb.toString());
            }
        } catch (Exception e) {
            LOGGER.warning("Could not save Divine Client config: " + e.getMessage());
        }
    }

    private static boolean parseBool(String json, String key, boolean def) {
        String search = "\"" + key + "\":";
        int idx = json.indexOf(search);
        if (idx == -1) return def;
        int start = idx + search.length();
        int end = json.indexOf(",", start);
        if (end == -1) end = json.indexOf("}", start);
        if (end == -1) end = json.length();
        String val = json.substring(start, end).trim();
        return "true".equalsIgnoreCase(val);
    }

    private static String parseString(String json, String key) {
        String search = "\"" + key + "\":";
        int idx = json.indexOf(search);
        if (idx == -1) return null;
        int firstQuote = json.indexOf("\"", idx + search.length());
        if (firstQuote == -1) return null;
        int secondQuote = json.indexOf("\"", firstQuote + 1);
        if (secondQuote == -1) return null;
        return json.substring(firstQuote + 1, secondQuote);
    }
}
