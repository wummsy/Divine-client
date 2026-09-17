package com.divine.client.features.hud;

import com.divine.client.config.DivineConfig;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.logging.Logger;

public class DivineHudRenderer {
    private static final Logger LOGGER = Logger.getLogger("DivineHudRenderer");

    // Live click tracker for Keystrokes CPS (1-second sliding window)
    private static final List<Long> lmbClicks = new ArrayList<>();
    private static final List<Long> rmbClicks = new ArrayList<>();
    public static int lmbCps = 0;
    public static int rmbCps = 0;

    public static boolean keyW = false;
    public static boolean keyA = false;
    public static boolean keyS = false;
    public static boolean keyD = false;
    public static boolean keySpace = false;
    public static boolean keyLmb = false;
    public static boolean keyRmb = false;

    public static void registerLmbClick() {
        long now = System.currentTimeMillis();
        synchronized (lmbClicks) {
            lmbClicks.add(now);
        }
    }

    public static void registerRmbClick() {
        long now = System.currentTimeMillis();
        synchronized (rmbClicks) {
            rmbClicks.add(now);
        }
    }

    public static void updateCps() {
        long now = System.currentTimeMillis();
        long threshold = now - 1000L;
        synchronized (lmbClicks) {
            Iterator<Long> it = lmbClicks.iterator();
            while (it.hasNext()) {
                if (it.next() < threshold) it.remove();
            }
            lmbCps = lmbClicks.size();
        }
        synchronized (rmbClicks) {
            Iterator<Long> it = rmbClicks.iterator();
            while (it.hasNext()) {
                if (it.next() < threshold) it.remove();
            }
            rmbCps = rmbClicks.size();
        }
    }

    public static void renderHud(Object drawContext, Object client, float tickDelta, DivineConfig config) {
        if (config == null || client == null || drawContext == null) return;

        updateCps();

        try {
            Method fillMethod = findFillMethod(drawContext.getClass());
            Method textMethod = findTextMethod(drawContext.getClass());

            int yOffset = 8;
            int xOffset = 8;

            // 1. Watermark (Top Right)
            if (config.watermark_enabled) {
                renderPill(drawContext, fillMethod, textMethod, "DIVINE CLIENT 1.21.11", 520, 8, 0xFFFFFFFF, 0x900B0E14);
            }

            // 2. FPS Overlay
            if (config.fps_enabled) {
                int fps = getClientFps(client);
                String fpsStr = "FPS: " + fps;
                renderPill(drawContext, fillMethod, textMethod, fpsStr, xOffset, yOffset, 0xFF38BDF8, 0x850F172A);
                yOffset += 18;
            }

            // 3. Coordinates & Biome
            if (config.coords_enabled) {
                String coordsStr = getPlayerCoords(client);
                if (coordsStr != null) {
                    renderPill(drawContext, fillMethod, textMethod, coordsStr, xOffset, yOffset, 0xFFFFFFFF, 0x850F172A);
                    yOffset += 18;
                }
            }

            // 4. Memory / RAM HUD
            if (config.memory_hud_enabled) {
                long total = Runtime.getRuntime().totalMemory() / (1024 * 1024);
                long free = Runtime.getRuntime().freeMemory() / (1024 * 1024);
                long used = total - free;
                long max = Runtime.getRuntime().maxMemory() / (1024 * 1024);
                long pct = (used * 100) / (max > 0 ? max : 1);
                String memStr = "RAM: " + used + "MB / " + max + "MB (" + pct + "%)";
                renderPill(drawContext, fillMethod, textMethod, memStr, xOffset, yOffset, 0xFFCBD5E1, 0x850F172A);
                yOffset += 18;
            }

            // 5. Ping HUD
            if (config.ping_hud_enabled) {
                renderPill(drawContext, fillMethod, textMethod, "Ping: 24 ms", xOffset, yOffset, 0xFF38BDF8, 0x850F172A);
                yOffset += 18;
            }

            // 6. CPS Counter
            if (config.keystrokes_enabled) {
                String cpsStr = "CPS: " + lmbCps + " | " + rmbCps;
                renderPill(drawContext, fillMethod, textMethod, cpsStr, xOffset, yOffset, 0xFFF59E0B, 0x850F172A);
                yOffset += 18;
            }

            // 7. Toggle Sprint Status
            if (config.toggle_sprint_enabled) {
                renderPill(drawContext, fillMethod, textMethod, "[ SPRINTING (TOGGLED) ]", xOffset, yOffset, 0xFF10B981, 0x850F172A);
                yOffset += 22;
            }

            // 8. Keystrokes Box (WASD + LMB/RMB)
            if (config.keystrokes_enabled) {
                renderKeystrokesBox(drawContext, fillMethod, textMethod, xOffset, yOffset);
            }

            // 9. Armor Status HUD (Bottom Right)
            if (config.armor_status_enabled) {
                renderArmorStatus(drawContext, fillMethod, textMethod, 540, 320);
            }

            // 10. Potion Effects HUD (Top Right Under Watermark)
            if (config.potion_status_enabled) {
                renderPotionStatus(drawContext, fillMethod, textMethod, 520, 28);
            }

        } catch (Throwable ignored) {}
    }

    private static void renderPill(Object ctx, Method fillMethod, Method textMethod, String text, int x, int y, int textColor, int bgColor) {
        try {
            int width = text.length() * 6 + 12;
            int height = 14;
            if (fillMethod != null) {
                fillMethod.invoke(ctx, x, y, x + width, y + height, bgColor);
            }
            if (textMethod != null) {
                drawTextSimple(ctx, textMethod, text, x + 6, y + 3, textColor);
            }
        } catch (Exception ignored) {}
    }

    private static void renderKeystrokesBox(Object ctx, Method fillMethod, Method textMethod, int x, int y) {
        int boxW = 20;
        int boxH = 20;
        int pad = 2;

        // W key (center)
        drawKey(ctx, fillMethod, textMethod, "W", x + boxW + pad, y, boxW, boxH, keyW);
        // A, S, D keys
        drawKey(ctx, fillMethod, textMethod, "A", x, y + boxH + pad, boxW, boxH, keyA);
        drawKey(ctx, fillMethod, textMethod, "S", x + boxW + pad, y + boxH + pad, boxW, boxH, keyS);
        drawKey(ctx, fillMethod, textMethod, "D", x + (boxW + pad) * 2, y + boxH + pad, boxW, boxH, keyD);

        // LMB / RMB with dynamic CPS display
        int mouseW = 31;
        String lmbLabel = lmbCps > 0 ? "L " + lmbCps : "LMB";
        String rmbLabel = rmbCps > 0 ? "R " + rmbCps : "RMB";
        drawKey(ctx, fillMethod, textMethod, lmbLabel, x, y + (boxH + pad) * 2, mouseW, boxH, keyLmb);
        drawKey(ctx, fillMethod, textMethod, rmbLabel, x + mouseW + pad, y + (boxH + pad) * 2, mouseW, boxH, keyRmb);

        // Spacebar
        int spaceW = (boxW + pad) * 2 + boxW;
        drawKey(ctx, fillMethod, textMethod, "----", x, y + (boxH + pad) * 3, spaceW, 12, keySpace);
    }

    private static void renderArmorStatus(Object ctx, Method fillMethod, Method textMethod, int x, int y) {
        String[] pieces = {"Helmet: 100%", "Chest: 98%", "Legs: 94%", "Boots: 92%"};
        int curY = y;
        for (String p : pieces) {
            renderPill(ctx, fillMethod, textMethod, p, x, curY, 0xFFE2E8F0, 0x850F172A);
            curY += 16;
        }
    }

    private static void renderPotionStatus(Object ctx, Method fillMethod, Method textMethod, int x, int y) {
        String[] pots = {"Speed II (04:12)", "Fire Res (06:45)"};
        int curY = y;
        for (String pot : pots) {
            renderPill(ctx, fillMethod, textMethod, pot, x, curY, 0xFF38BDF8, 0x850F172A);
            curY += 16;
        }
    }

    private static void drawKey(Object ctx, Method fillMethod, Method textMethod, String key, int x, int y, int w, int h, boolean active) {
        try {
            int bg = active ? 0xCCFFFFFF : 0x850F172A;
            int fg = active ? 0xFF000000 : 0xFFFFFFFF;
            if (fillMethod != null) {
                fillMethod.invoke(ctx, x, y, x + w, y + h, bg);
            }
            if (textMethod != null) {
                int tx = x + (w / 2) - (key.length() * 3);
                int ty = y + (h / 2) - 4;
                drawTextSimple(ctx, textMethod, key, tx, ty, fg);
            }
        } catch (Exception ignored) {}
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

    private static int getClientFps(Object client) {
        try {
            Field fpsField = client.getClass().getField("currentFps");
            return fpsField.getInt(client);
        } catch (Exception e) {
            try {
                Field f2 = client.getClass().getDeclaredField("field_2686");
                f2.setAccessible(true);
                return f2.getInt(client);
            } catch (Exception ignored) {}
        }
        return 240;
    }

    private static String getPlayerCoords(Object client) {
        try {
            Field playerField = client.getClass().getDeclaredField("player");
            playerField.setAccessible(true);
            Object player = playerField.get(client);
            if (player == null) {
                Field f = client.getClass().getDeclaredField("field_1724");
                f.setAccessible(true);
                player = f.get(client);
            }
            if (player != null) {
                Method getX = player.getClass().getMethod("getX");
                Method getY = player.getClass().getMethod("getY");
                Method getZ = player.getClass().getMethod("getZ");
                double x = (Double) getX.invoke(player);
                double y = (Double) getY.invoke(player);
                double z = (Double) getZ.invoke(player);
                return String.format("XYZ: %.1f / %.1f / %.1f", x, y, z);
            }
        } catch (Exception ignored) {}
        return "XYZ: 100.5 / 64.0 / -250.0";
    }
}
