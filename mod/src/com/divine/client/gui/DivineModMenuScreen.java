package com.divine.client.gui;

import com.divine.client.config.DivineConfig;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

public class DivineModMenuScreen {

    public static boolean isOpen = false;
    private static Object parentScreen = null;
    private static int selectedCategory = 0; // 0=ALL, 1=HUD, 2=PVP, 3=RENDER, 4=GENERAL
    private static int scrollY = 0;

    public static class ModEntry {
        public String id;
        public String title;
        public String category;
        public String description;

        public ModEntry(String id, String title, String category, String description) {
            this.id = id;
            this.title = title;
            this.category = category;
            this.description = description;
        }
    }

    public static final List<ModEntry> MODS = new ArrayList<>();

    static {
        MODS.add(new ModEntry("fps", "FPS Display", "HUD", "Displays live frames per second with custom styling."));
        MODS.add(new ModEntry("coords", "Coordinates", "HUD", "Shows player XYZ position, facing direction, and current biome."));
        MODS.add(new ModEntry("keystrokes", "Keystrokes HUD", "PVP", "Visualizes WASD, Space, LMB/RMB CPS with live animations."));
        MODS.add(new ModEntry("fullbright", "Fullbright Gamma", "RENDER", "Provides clear night vision and cave illumination without torches."));
        MODS.add(new ModEntry("zoom", "Smooth Zoom", "RENDER", "Smooth cinematic zoom holding key C with FOV transition."));
        MODS.add(new ModEntry("toggle_sprint", "Toggle Sprint", "PVP", "Maintains sprinting automatically without holding key."));
        MODS.add(new ModEntry("armor_status", "Armor Status", "HUD", "Displays durability bars, counts, and damage for equipped armor."));
        MODS.add(new ModEntry("potion_status", "Potion Status", "HUD", "Shows active status effects, amplifier, and countdown timers."));
        MODS.add(new ModEntry("low_fire", "Low Fire", "RENDER", "Lowers on-screen fire height for unobstructed combat vision."));
        MODS.add(new ModEntry("small_totem", "Small Totem", "RENDER", "Reduces first-person totem and shield hand models."));
        MODS.add(new ModEntry("memory", "Memory / RAM", "HUD", "Shows JVM heap memory allocation and usage percentage."));
        MODS.add(new ModEntry("ping", "Ping Display", "HUD", "Shows real-time latency to current multiplayer server."));
        MODS.add(new ModEntry("watermark", "Divine Logo", "GENERAL", "Displays the official Divine Client animated emblem."));
        MODS.add(new ModEntry("compass", "Top Compass", "HUD", "Navigational direction bar with cardinal degree ticks."));
    }

    public static void open(Object client, Object parent, DivineConfig config) {
        isOpen = true;
        parentScreen = parent;
    }

    public static void close() {
        isOpen = false;
    }

    public static void render(Object drawContext, Object client, int width, int height, int mouseX, int mouseY, DivineConfig config) {
        if (!isOpen || drawContext == null || config == null) return;

        try {
            Method fillMethod = findFillMethod(drawContext.getClass());
            Method textMethod = findTextMethod(drawContext.getClass());

            // 1. Semi-translucent dark blurred overlay backdrop
            if (fillMethod != null) {
                fillMethod.invoke(drawContext, 0, 0, width, height, 0xCC06080F);
            }

            // 2. Mod Menu Dialog Panel (Centered)
            int panelW = Math.min(680, width - 40);
            int panelH = Math.min(420, height - 40);
            int px = (width - panelW) / 2;
            int py = (height - panelH) / 2;

            if (fillMethod != null) {
                // Background & border
                fillMethod.invoke(drawContext, px, py, px + panelW, py + panelH, 0xF00D111A);
                fillMethod.invoke(drawContext, px, py, px + panelW, py + 1, 0xFF38BDF8); // Top cyan accent
                fillMethod.invoke(drawContext, px, py + panelH - 1, px + panelW, py + panelH, 0x44FFFFFF);
                fillMethod.invoke(drawContext, px, py, px + 1, py + panelH, 0x44FFFFFF);
                fillMethod.invoke(drawContext, px + panelW - 1, py, px + panelW, py + panelH, 0x44FFFFFF);
            }

            // 3. Header Bar
            int headerY = py + 12;
            if (textMethod != null) {
                drawTextSimple(drawContext, textMethod, "DIVINE CLIENT MODS", px + 18, headerY, 0xFFFFFFFF);
                drawTextSimple(drawContext, textMethod, "v4.0.0 - QoL Suite", px + 145, headerY + 1, 0xFF94A3B8);
            }

            // Close button [X] at top right
            int closeBtnX = px + panelW - 24;
            int closeBtnY = py + 10;
            boolean closeHover = isMouseOver(mouseX, mouseY, closeBtnX, closeBtnY, 14, 14);
            if (textMethod != null) {
                drawTextSimple(drawContext, textMethod, "X", closeBtnX + 2, closeBtnY, closeHover ? 0xFFEF4444 : 0xFF94A3B8);
            }

            // 4. Category Tabs Bar: ALL | HUD | PVP | RENDER | GENERAL
            String[] cats = {"ALL", "HUD", "PVP", "RENDER", "GENERAL"};
            int tabX = px + 18;
            int tabY = py + 34;
            for (int i = 0; i < cats.length; i++) {
                String cat = cats[i];
                int tabW = cat.length() * 7 + 16;
                boolean isSel = (i == selectedCategory);
                boolean isHover = isMouseOver(mouseX, mouseY, tabX, tabY, tabW, 16);

                int bg = isSel ? 0xFF1E293B : (isHover ? 0x661E293B : 0x00000000);
                int fg = isSel ? 0xFFFFFFFF : 0xFF94A3B8;

                if (fillMethod != null && isSel) {
                    fillMethod.invoke(drawContext, tabX, tabY, tabX + tabW, tabY + 16, bg);
                    fillMethod.invoke(drawContext, tabX, tabY + 15, tabX + tabW, tabY + 16, 0xFF38BDF8);
                }
                if (textMethod != null) {
                    drawTextSimple(drawContext, textMethod, cat, tabX + 8, tabY + 3, fg);
                }
                tabX += tabW + 6;
            }

            // 5. Mod Cards Grid (2 Columns)
            int gridX = px + 18;
            int gridY = py + 60;
            int cardW = (panelW - 48) / 2;
            int cardH = 68;

            int col = 0;
            int row = 0;

            for (ModEntry mod : MODS) {
                if (selectedCategory != 0) {
                    String req = cats[selectedCategory];
                    if (!mod.category.equalsIgnoreCase(req)) continue;
                }

                int cx = gridX + col * (cardW + 12);
                int cy = gridY + row * (cardH + 10);

                if (cy + cardH > py + panelH - 10) break; // clip if overflowing

                boolean enabled = config.isModEnabled(mod.id);
                boolean cardHover = isMouseOver(mouseX, mouseY, cx, cy, cardW, cardH);

                // Render Card Box
                if (fillMethod != null) {
                    int cardBg = cardHover ? 0xFF161D2B : 0xFF111622;
                    int cardBorder = enabled ? 0x8810B981 : 0x33FFFFFF;
                    fillMethod.invoke(drawContext, cx, cy, cx + cardW, cy + cardH, cardBg);
                    // outline
                    fillMethod.invoke(drawContext, cx, cy, cx + cardW, cy + 1, cardBorder);
                    fillMethod.invoke(drawContext, cx, cy + cardH - 1, cx + cardW, cy + cardH, cardBorder);
                    fillMethod.invoke(drawContext, cx, cy, cx + 1, cy + cardH, cardBorder);
                    fillMethod.invoke(drawContext, cx + cardW - 1, cy, cx + cardW, cy + cardH, cardBorder);
                }

                // Card Title & Category Tag
                if (textMethod != null) {
                    drawTextSimple(drawContext, textMethod, mod.title, cx + 10, cy + 8, 0xFFFFFFFF);
                    drawTextSimple(drawContext, textMethod, "[" + mod.category + "]", cx + cardW - (mod.category.length() * 6) - 24, cy + 8, 0xFF64748B);
                    // Description
                    String desc = mod.description;
                    if (desc.length() > 38) desc = desc.substring(0, 35) + "...";
                    drawTextSimple(drawContext, textMethod, desc, cx + 10, cy + 22, 0xFF94A3B8);
                }

                // Bottom Toggle Bar: Green ENABLED vs Red DISABLED
                int toggleY = cy + cardH - 18;
                int toggleW = cardW - 16;
                int toggleBg = enabled ? 0xFF10B981 : 0xFFEF4444;
                String toggleLabel = enabled ? "ENABLED" : "DISABLED";

                if (fillMethod != null) {
                    fillMethod.invoke(drawContext, cx + 8, toggleY, cx + 8 + toggleW, toggleY + 12, toggleBg);
                }
                if (textMethod != null) {
                    int tx = cx + 8 + (toggleW / 2) - (toggleLabel.length() * 3);
                    drawTextSimple(drawContext, textMethod, toggleLabel, tx, toggleY + 2, 0xFFFFFFFF);
                }

                col++;
                if (col >= 2) {
                    col = 0;
                    row++;
                }
            }

        } catch (Throwable ignored) {}
    }

    public static boolean handleClick(double mouseX, double mouseY, int button, int width, int height, DivineConfig config) {
        if (!isOpen || button != 0 || config == null) return false;

        try {
            int panelW = Math.min(680, width - 40);
            int panelH = Math.min(420, height - 40);
            int px = (width - panelW) / 2;
            int py = (height - panelH) / 2;

            // Close button click
            int closeBtnX = px + panelW - 24;
            int closeBtnY = py + 10;
            if (isMouseOver((int) mouseX, (int) mouseY, closeBtnX, closeBtnY, 16, 16)) {
                close();
                return true;
            }

            // Category Tab Click
            String[] cats = {"ALL", "HUD", "PVP", "RENDER", "GENERAL"};
            int tabX = px + 18;
            int tabY = py + 34;
            for (int i = 0; i < cats.length; i++) {
                String cat = cats[i];
                int tabW = cat.length() * 7 + 16;
                if (isMouseOver((int) mouseX, (int) mouseY, tabX, tabY, tabW, 16)) {
                    selectedCategory = i;
                    return true;
                }
                tabX += tabW + 6;
            }

            // Mod Cards Click
            int gridX = px + 18;
            int gridY = py + 60;
            int cardW = (panelW - 48) / 2;
            int cardH = 68;

            int col = 0;
            int row = 0;

            for (ModEntry mod : MODS) {
                if (selectedCategory != 0) {
                    String req = cats[selectedCategory];
                    if (!mod.category.equalsIgnoreCase(req)) continue;
                }

                int cx = gridX + col * (cardW + 12);
                int cy = gridY + row * (cardH + 10);

                if (cy + cardH > py + panelH - 10) break;

                if (isMouseOver((int) mouseX, (int) mouseY, cx, cy, cardW, cardH)) {
                    config.toggleMod(mod.id);
                    return true;
                }

                col++;
                if (col >= 2) {
                    col = 0;
                    row++;
                }
            }

        } catch (Throwable ignored) {}
        return false;
    }

    private static boolean isMouseOver(int mx, int my, int x, int y, int w, int h) {
        return mx >= x && mx <= x + w && my >= y && my <= y + h;
    }

    private static void drawTextSimple(Object ctx, Method textMethod, String text, int x, int y, int color) {
        try {
            Class<?>[] pTypes = textMethod.getParameterTypes();
            if (pTypes.length == 5) {
                textMethod.invoke(ctx, null, text, x, y, color);
            } else if (pTypes.length == 4) {
                textMethod.invoke(ctx, text, x, y, color);
            }
        } catch (Exception ignored) {}
    }

    private static Method findFillMethod(Class<?> clazz) {
        for (Method m : clazz.getMethods()) {
            if ((m.getName().equals("fill") || m.getName().equals("method_25294")) && m.getParameterCount() >= 5) {
                return m;
            }
        }
        return null;
    }

    private static Method findTextMethod(Class<?> clazz) {
        for (Method m : clazz.getMethods()) {
            if ((m.getName().equals("drawText") || m.getName().equals("method_27535") || m.getName().equals("drawTextWithShadow")) && m.getParameterCount() >= 4) {
                return m;
            }
        }
        return null;
    }
}
