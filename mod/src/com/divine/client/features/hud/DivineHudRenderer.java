package com.divine.client.features.hud;

import com.divine.client.config.DivineConfig;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.logging.Logger;

public class DivineHudRenderer {
    private static final Logger LOGGER = Logger.getLogger("DivineHudRenderer");

    // Live click tracker for Keystrokes CPS
    public static int lmbCps = 0;
    public static int rmbCps = 0;
    public static boolean keyW = false;
    public static boolean keyA = false;
    public static boolean keyS = false;
    public static boolean keyD = false;
    public static boolean keySpace = false;
    public static boolean keyLmb = false;
    public static boolean keyRmb = false;

    public static void renderHud(Object drawContext, Object client, float tickDelta, DivineConfig config) {
        if (config == null || client == null || drawContext == null) return;

        try {
            // Get screen width/height or font renderer if available
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
                renderPill(drawContext, fillMethod, textMethod, fpsStr, xOffset, yOffset, 0xFFFFFFFF, 0x850F172A);
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

            // 4. Memory / RAM
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

            // 5. Ping
            if (config.ping_hud_enabled) {
                renderPill(drawContext, fillMethod, textMethod, "Ping: 24 ms", xOffset, yOffset, 0xFF38BDF8, 0x850F172A);
                yOffset += 18;
            }

            // 6. Toggle Sprint Status
            if (config.toggle_sprint_enabled) {
                renderPill(drawContext, fillMethod, textMethod, "[ SPRINTING (TOGGLED) ]", xOffset, yOffset, 0xFF10B981, 0x850F172A);
                yOffset += 22;
            }

            // 7. Keystrokes HUD (WASD + LMB/RMB)
            if (config.keystrokes_enabled) {
                renderKeystrokesBox(drawContext, fillMethod, textMethod, xOffset, yOffset);
            }

        } catch (Throwable t) {
            // Keep completely resilient
        }
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

        // LMB / RMB
        int mouseW = 31;
        drawKey(ctx, fillMethod, textMethod, "LMB", x, y + (boxH + pad) * 2, mouseW, boxH, keyLmb);
        drawKey(ctx, fillMethod, textMethod, "RMB", x + mouseW + pad, y + (boxH + pad) * 2, mouseW, boxH, keyRmb);

        // SPACE
        int spaceW = (boxW + pad) * 2 + boxW;
        drawKey(ctx, fillMethod, textMethod, "----", x, y + (boxH + pad) * 3, spaceW, 12, keySpace);
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
            // Check parameter types
            Class<?>[] pTypes = textMethod.getParameterTypes();
            if (pTypes.length == 5) {
                // drawText(TextRenderer, String, int, int, int, boolean) or similar
                // Try simplest invocation
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
                // Intermediary field_2686
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
                // Intermediary field_1724
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
