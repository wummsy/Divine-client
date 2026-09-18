package com.divine.client.gui;

import com.divine.client.config.DivineConfig;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Collection;
import java.util.List;
import java.util.logging.Logger;

public class DivineTitleScreen {
    private static final Logger LOGGER = Logger.getLogger("DivineTitleScreen");

    // Track active hovered button:
    // 0 = SINGLEPLAYER, 1 = MULTIPLAYER, 2 = COSMETICS, 3 = DIVINE MODS, 4 = OPTIONS, 5 = QUIT
    public static int hoveredButton = -1;

    public static void onScreenInit(Object client, Object screen, int width, int height) {
        if (screen == null) return;
        try {
            // 1. Remove all vanilla buttons and widgets
            clearVanillaWidgets(screen);

            // 2. Remove yellow splash text
            removeSplashText(screen);

        } catch (Throwable t) {
            LOGGER.warning("Could not completely clear vanilla TitleScreen: " + t.getMessage());
        }
    }

    public static void clearVanillaWidgets(Object screen) {
        if (screen == null) return;
        try {
            Class<?> sc = screen.getClass();
            while (sc != null && sc != Object.class) {
                for (Field f : sc.getDeclaredFields()) {
                    f.setAccessible(true);
                    Object val = f.get(screen);
                    if (val instanceof Collection) {
                        try {
                            ((Collection<?>) val).clear();
                        } catch (Exception ignored) {}
                    }
                }
                sc = sc.getSuperclass();
            }
        } catch (Throwable ignored) {}
    }

    private static void removeSplashText(Object screen) {
        if (screen == null) return;
        try {
            Class<?> sc = screen.getClass();
            for (Field f : sc.getDeclaredFields()) {
                if (f.getType().getSimpleName().contains("Splash") || f.getName().contains("splash")) {
                    f.setAccessible(true);
                    f.set(screen, null);
                }
            }
        } catch (Throwable ignored) {}
    }

    public static void renderCustomMenu(Object drawContext, Object client, Object screen, int mouseX, int mouseY, float delta, DivineConfig config) {
        if (drawContext == null || screen == null) return;

        try {
            int width = getScreenWidth(screen);
            int height = getScreenHeight(screen);
            if (width <= 0) width = 854;
            if (height <= 0) height = 480;

            Method fillMethod = findFillMethod(drawContext.getClass());
            Method textMethod = findTextMethod(drawContext.getClass());

            // 1. Draw 100% Flat Dark Obsidian 2D Background (NO PANORAMA DISTORTION)
            if (fillMethod != null) {
                fillMethod.invoke(drawContext, 0, 0, width, height, 0xFF080B11); // Deep Obsidian
                // Subtle top atmospheric glow
                fillMethod.invoke(drawContext, 0, 0, width, 120, 0x18FFFFFF);
            }

            // 2. Draw Centered Divine Client Header Typography
            int cx = width / 2;
            int logoY = height / 4 - 30;
            if (textMethod != null) {
                drawCenteredText(drawContext, textMethod, "DIVINE CLIENT", cx, logoY, 0xFFFFFFFF);
                drawCenteredText(drawContext, textMethod, "High-Performance Client Edition 1.21.11", cx, logoY + 14, 0xFF94A3B8);
            }

            // 3. Render Custom Clean Divine-Style Main Buttons
            int btnW = 200;
            int btnH = 26;
            int startY = height / 2 - 25;

            // Button 0: SINGLEPLAYER
            int spY = startY;
            boolean spHover = isMouseOver(mouseX, mouseY, cx - btnW / 2, spY, btnW, btnH);
            drawMenuButton(drawContext, fillMethod, textMethod, "SINGLEPLAYER", cx - btnW / 2, spY, btnW, btnH, spHover);

            // Button 1: MULTIPLAYER
            int mpY = startY + 34;
            boolean mpHover = isMouseOver(mouseX, mouseY, cx - btnW / 2, mpY, btnW, btnH);
            drawMenuButton(drawContext, fillMethod, textMethod, "MULTIPLAYER", cx - btnW / 2, mpY, btnW, btnH, mpHover);

            // 4. Render Bottom Quick Row: COSMETICS | BUILDER | DIVINE MODS | OPTIONS | QUIT
            int quickBtnW = 82;
            int quickBtnH = 22;
            int quickTotalW = (quickBtnW * 5) + (6 * 4);
            int quickStartX = cx - quickTotalW / 2;
            int quickY = height - 44;

            // Button 2: COSMETICS
            boolean cosHover = isMouseOver(mouseX, mouseY, quickStartX, quickY, quickBtnW, quickBtnH);
            drawMenuButton(drawContext, fillMethod, textMethod, "COSMETICS", quickStartX, quickY, quickBtnW, quickBtnH, cosHover);

            // Button 3: BUILDER TOOLS
            int buildX = quickStartX + quickBtnW + 6;
            boolean buildHover = isMouseOver(mouseX, mouseY, buildX, quickY, quickBtnW, quickBtnH);
            drawMenuButton(drawContext, fillMethod, textMethod, "BUILDER", buildX, quickY, quickBtnW, quickBtnH, buildHover);

            // Button 4: DIVINE MODS
            int modsX = buildX + quickBtnW + 6;
            boolean modsHover = isMouseOver(mouseX, mouseY, modsX, quickY, quickBtnW, quickBtnH);
            drawMenuButton(drawContext, fillMethod, textMethod, "DIVINE MODS", modsX, quickY, quickBtnW, quickBtnH, modsHover);

            // Button 5: OPTIONS
            int optX = modsX + quickBtnW + 6;
            boolean optHover = isMouseOver(mouseX, mouseY, optX, quickY, quickBtnW, quickBtnH);
            drawMenuButton(drawContext, fillMethod, textMethod, "OPTIONS", optX, quickY, quickBtnW, quickBtnH, optHover);

            // Button 6: QUIT
            int quitX = optX + quickBtnW + 6;
            boolean quitHover = isMouseOver(mouseX, mouseY, quitX, quickY, quickBtnW, quickBtnH);
            drawMenuButton(drawContext, fillMethod, textMethod, "QUIT", quitX, quickY, quickBtnW, quickBtnH, quitHover);

            // 5. Footer info
            if (textMethod != null) {
                drawTextSimple(drawContext, textMethod, "Divine Client v4.0.0 (Fabric 1.21.11)", 10, height - 16, 0xFF64748B);
                String serverMsg = (config != null) ? config.server_status : "cant connect to server";
                int col = serverMsg.contains("Connected") ? 0xFF10B981 : 0xFF94A3B8;
                drawTextSimple(drawContext, textMethod, serverMsg, width - (serverMsg.length() * 6) - 14, height - 16, col);
            }

            // Update hovered index
            if (spHover) hoveredButton = 0;
            else if (mpHover) hoveredButton = 1;
            else if (cosHover) hoveredButton = 2;
            else if (modsHover) hoveredButton = 3;
            else if (optHover) hoveredButton = 4;
            else if (quitHover) hoveredButton = 5;
            else hoveredButton = -1;

        } catch (Throwable ignored) {}
    }

    public static boolean handleMouseClick(Object client, Object screen, double mouseX, double mouseY, int button, DivineConfig config) {
        if (button != 0 || screen == null || client == null) return false;

        try {
            int width = getScreenWidth(screen);
            int height = getScreenHeight(screen);
            int cx = width / 2;
            int btnW = 200;
            int btnH = 26;
            int startY = height / 2 - 25;

            // 0: SINGLEPLAYER
            if (isMouseOver((int) mouseX, (int) mouseY, cx - btnW / 2, startY, btnW, btnH)) {
                openScreen(client, screen, "net.minecraft.client.gui.screen.world.SelectWorldScreen", "net.minecraft.class_526");
                return true;
            }

            // 1: MULTIPLAYER
            if (isMouseOver((int) mouseX, (int) mouseY, cx - btnW / 2, startY + 34, btnW, btnH)) {
                openScreen(client, screen, "net.minecraft.client.gui.screen.multiplayer.MultiplayerScreen", "net.minecraft.class_500");
                return true;
            }

            int quickBtnW = 90;
            int quickBtnH = 22;
            int quickTotalW = (quickBtnW * 4) + (8 * 3);
            int quickStartX = cx - quickTotalW / 2;
            int quickY = height - 44;

            // 2: COSMETICS
            if (isMouseOver((int) mouseX, (int) mouseY, quickStartX, quickY, quickBtnW, quickBtnH)) {
                DivineCosmeticsScreen.open(client, screen, config);
                return true;
            }

            // 3: DIVINE MODS
            int modsX = quickStartX + quickBtnW + 8;
            if (isMouseOver((int) mouseX, (int) mouseY, modsX, quickY, quickBtnW, quickBtnH)) {
                DivineModMenuScreen.open(client, screen, config);
                return true;
            }

            // 4: OPTIONS
            int optX = modsX + quickBtnW + 8;
            if (isMouseOver((int) mouseX, (int) mouseY, optX, quickY, quickBtnW, quickBtnH)) {
                openOptionsScreen(client, screen);
                return true;
            }

            // 5: QUIT
            int quitX = optX + quickBtnW + 8;
            if (isMouseOver((int) mouseX, (int) mouseY, quitX, quickY, quickBtnW, quickBtnH)) {
                Method stop = client.getClass().getMethod("scheduleStop");
                stop.invoke(client);
                return true;
            }
        } catch (Throwable t) {
            LOGGER.warning("Menu click error: " + t.getMessage());
        }
        return false;
    }

    private static void drawMenuButton(Object ctx, Method fillMethod, Method textMethod, String label, int x, int y, int w, int h, boolean hover) {
        try {
            int bg = hover ? 0xEE1E293B : 0xAA0F172A;
            int border = hover ? 0xFFFFFFFF : 0x44FFFFFF;
            int textCol = hover ? 0xFFFFFFFF : 0xFFE2E8F0;

            if (fillMethod != null) {
                // Background
                fillMethod.invoke(ctx, x, y, x + w, y + h, bg);
                // Top/bottom/left/right border outline
                fillMethod.invoke(ctx, x, y, x + w, y + 1, border);
                fillMethod.invoke(ctx, x, y + h - 1, x + w, y + h, border);
                fillMethod.invoke(ctx, x, y, x + 1, y + h, border);
                fillMethod.invoke(ctx, x + w - 1, y, x + w, y + h, border);
            }

            if (textMethod != null) {
                int tx = x + (w / 2) - (label.length() * 3);
                int ty = y + (h / 2) - 4;
                drawTextSimple(ctx, textMethod, label, tx, ty, textCol);
            }
        } catch (Exception ignored) {}
    }

    private static void openScreen(Object client, Object parent, String yarnClass, String interClass) {
        try {
            Class<?> targetCls = null;
            try {
                targetCls = Class.forName(yarnClass);
            } catch (ClassNotFoundException e) {
                targetCls = Class.forName(interClass);
            }

            Constructor<?> ctor = null;
            for (Constructor<?> c : targetCls.getConstructors()) {
                if (c.getParameterCount() == 1) {
                    ctor = c;
                    break;
                }
            }
            if (ctor != null) {
                Object newScreen = ctor.newInstance(parent);
                Method setScreen = client.getClass().getMethod("setScreen", Class.forName("net.minecraft.client.gui.screen.Screen"));
                setScreen.invoke(client, newScreen);
            }
        } catch (Throwable t) {
            LOGGER.warning("Could not open screen " + yarnClass + ": " + t.getMessage());
        }
    }

    private static void openOptionsScreen(Object client, Object parent) {
        try {
            Field optField = client.getClass().getDeclaredField("options");
            optField.setAccessible(true);
            Object options = optField.get(client);

            Class<?> targetCls = null;
            try {
                targetCls = Class.forName("net.minecraft.client.gui.screen.option.OptionsScreen");
            } catch (ClassNotFoundException e) {
                targetCls = Class.forName("net.minecraft.class_429");
            }

            Constructor<?> ctor = null;
            for (Constructor<?> c : targetCls.getConstructors()) {
                if (c.getParameterCount() == 2) {
                    ctor = c;
                    break;
                }
            }
            if (ctor != null) {
                Object newScreen = ctor.newInstance(parent, options);
                Method setScreen = client.getClass().getMethod("setScreen", Class.forName("net.minecraft.client.gui.screen.Screen"));
                setScreen.invoke(client, newScreen);
            }
        } catch (Throwable t) {
            LOGGER.warning("Could not open OptionsScreen: " + t.getMessage());
        }
    }

    private static boolean isMouseOver(int mx, int my, int x, int y, int w, int h) {
        return mx >= x && mx <= x + w && my >= y && my <= y + h;
    }

    private static int getScreenWidth(Object screen) {
        try {
            Field f = screen.getClass().getField("width");
            return f.getInt(screen);
        } catch (Exception e) {
            try {
                Field f2 = screen.getClass().getDeclaredField("field_22789");
                f2.setAccessible(true);
                return f2.getInt(screen);
            } catch (Exception ignored) {}
        }
        return 854;
    }

    private static int getScreenHeight(Object screen) {
        try {
            Field f = screen.getClass().getField("height");
            return f.getInt(screen);
        } catch (Exception e) {
            try {
                Field f2 = screen.getClass().getDeclaredField("field_22790");
                f2.setAccessible(true);
                return f2.getInt(screen);
            } catch (Exception ignored) {}
        }
        return 480;
    }

    private static void drawCenteredText(Object ctx, Method textMethod, String text, int cx, int y, int color) {
        int tx = cx - (text.length() * 3);
        drawTextSimple(ctx, textMethod, text, tx, y, color);
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
