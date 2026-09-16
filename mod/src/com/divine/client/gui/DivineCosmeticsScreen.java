package com.divine.client.gui;

import com.divine.client.config.DivineConfig;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

public class DivineCosmeticsScreen {
    public static boolean isOpen = false;
    private static Object parentScreen = null;

    public static class CloakEntry {
        public String id;
        public String name;
        public String tier;
        public String description;

        public CloakEntry(String id, String name, String tier, String description) {
            this.id = id;
            this.name = name;
            this.tier = tier;
            this.description = description;
        }
    }

    public static final List<CloakEntry> CLOAKS = new ArrayList<>();

    static {
        CLOAKS.add(new CloakEntry("booster", "Booster Cloak", "BOOSTER EXCLUSIVE", "Unlocked via code BOOSTER2026. Glowing celestial wings with animated sun trails."));
        CLOAKS.add(new CloakEntry("cosmic", "Cosmic Cloak", "LEGENDARY", "Deep nebula starfield animation with pulsing galaxy core."));
        CLOAKS.add(new CloakEntry("eclipse", "Eclipse Cloak", "MYTHIC", "Solar corona dark cloak with glowing gold edge embroidery."));
        CLOAKS.add(new CloakEntry("staff", "Divine Staff Cloak", "DEVELOPER", "Official verified Divine Client creator and developer cloak."));
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

            // 1. Dark overlay
            if (fillMethod != null) {
                fillMethod.invoke(drawContext, 0, 0, width, height, 0xCC06080F);
            }

            // 2. Dialog box
            int panelW = Math.min(640, width - 40);
            int panelH = Math.min(380, height - 40);
            int px = (width - panelW) / 2;
            int py = (height - panelH) / 2;

            if (fillMethod != null) {
                fillMethod.invoke(drawContext, px, py, px + panelW, py + panelH, 0xF00D111A);
                fillMethod.invoke(drawContext, px, py, px + panelW, py + 1, 0xFFF59E0B); // Gold top accent
                fillMethod.invoke(drawContext, px, py + panelH - 1, px + panelW, py + panelH, 0x44FFFFFF);
                fillMethod.invoke(drawContext, px, py, px + 1, py + panelH, 0x44FFFFFF);
                fillMethod.invoke(drawContext, px + panelW - 1, py, px + panelW, py + panelH, 0x44FFFFFF);
            }

            // 3. Header
            int headerY = py + 14;
            if (textMethod != null) {
                drawTextSimple(drawContext, textMethod, "DIVINE COSMETICS & CLOAKS", px + 18, headerY, 0xFFFFFFFF);
                drawTextSimple(drawContext, textMethod, "Equip synced cloaks and nametag badges", px + 18, headerY + 14, 0xFF94A3B8);
            }

            // Close button [X]
            int closeBtnX = px + panelW - 24;
            int closeBtnY = py + 12;
            boolean closeHover = isMouseOver(mouseX, mouseY, closeBtnX, closeBtnY, 14, 14);
            if (textMethod != null) {
                drawTextSimple(drawContext, textMethod, "X", closeBtnX + 2, closeBtnY, closeHover ? 0xFFEF4444 : 0xFF94A3B8);
            }

            // 4. Cloaks Grid
            int gridX = px + 18;
            int gridY = py + 56;
            int cardW = (panelW - 48) / 2;
            int cardH = 74;

            int col = 0;
            int row = 0;

            for (CloakEntry cloak : CLOAKS) {
                int cx = gridX + col * (cardW + 12);
                int cy = gridY + row * (cardH + 10);

                boolean isEquipped = cloak.id.equalsIgnoreCase(config.equipped_cloak);
                boolean isUnlocked = config.unlocked_cloaks.contains(cloak.id);
                boolean cardHover = isMouseOver(mouseX, mouseY, cx, cy, cardW, cardH);

                if (fillMethod != null) {
                    int cardBg = cardHover ? 0xFF1B2232 : 0xFF121724;
                    int cardBorder = isEquipped ? 0xFFF59E0B : 0x33FFFFFF;
                    fillMethod.invoke(drawContext, cx, cy, cx + cardW, cy + cardH, cardBg);
                    fillMethod.invoke(drawContext, cx, cy, cx + cardW, cy + 1, cardBorder);
                    fillMethod.invoke(drawContext, cx, cy + cardH - 1, cx + cardW, cy + cardH, cardBorder);
                    fillMethod.invoke(drawContext, cx, cy, cx + 1, cy + cardH, cardBorder);
                    fillMethod.invoke(drawContext, cx + cardW - 1, cy, cx + cardW, cy + cardH, cardBorder);
                }

                if (textMethod != null) {
                    drawTextSimple(drawContext, textMethod, cloak.name, cx + 10, cy + 8, 0xFFFFFFFF);
                    drawTextSimple(drawContext, textMethod, "[" + cloak.tier + "]", cx + 10, cy + 22, 0xFFF59E0B);
                }

                // Equip / Unequip Toggle Bar
                int toggleY = cy + cardH - 18;
                int toggleW = cardW - 16;
                int toggleBg = isEquipped ? 0xFF10B981 : (isUnlocked ? 0xFF3B82F6 : 0xFF475569);
                String toggleLabel = isEquipped ? "EQUIPPED" : (isUnlocked ? "EQUIP" : "LOCKED");

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
            int panelW = Math.min(640, width - 40);
            int panelH = Math.min(380, height - 40);
            int px = (width - panelW) / 2;
            int py = (height - panelH) / 2;

            int closeBtnX = px + panelW - 24;
            int closeBtnY = py + 12;
            if (isMouseOver((int) mouseX, (int) mouseY, closeBtnX, closeBtnY, 16, 16)) {
                close();
                return true;
            }

            int gridX = px + 18;
            int gridY = py + 56;
            int cardW = (panelW - 48) / 2;
            int cardH = 74;

            int col = 0;
            int row = 0;

            for (CloakEntry cloak : CLOAKS) {
                int cx = gridX + col * (cardW + 12);
                int cy = gridY + row * (cardH + 10);

                if (isMouseOver((int) mouseX, (int) mouseY, cx, cy, cardW, cardH)) {
                    if (config.unlocked_cloaks.contains(cloak.id)) {
                        if (cloak.id.equalsIgnoreCase(config.equipped_cloak)) {
                            config.equipped_cloak = "none";
                        } else {
                            config.equipped_cloak = cloak.id;
                        }
                        config.save();
                        return true;
                    }
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
