package com.divine.client;

import net.fabricmc.api.ClientModInitializer;
import com.divine.client.bridge.DivineIpcBridge;
import com.divine.client.config.DivineConfig;
import com.divine.client.features.hud.DivineHudRenderer;
import com.divine.client.features.movement.MovementFeatures;
import com.divine.client.features.render.RenderFeatures;
import com.divine.client.gui.DivineCosmeticsScreen;
import com.divine.client.gui.DivineModMenuScreen;
import com.divine.client.gui.DivineTitleScreen;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.logging.Logger;

public class DivineClient implements ClientModInitializer {
    public static final String MOD_ID = "divineclient";
    public static final Logger LOGGER = Logger.getLogger("DivineClient");
    public static DivineConfig CONFIG;
    public static Object minecraftInstance = null;

    // GLFW Key Constants
    public static final int GLFW_KEY_RIGHT_SHIFT = 344;
    public static final int GLFW_KEY_M = 77;
    public static final int GLFW_KEY_G = 71;
    public static final int GLFW_KEY_F6 = 295;
    public static final int GLFW_KEY_C = 67;
    public static final int GLFW_KEY_R = 82;

    private static boolean rShiftLastState = false;
    private static boolean mKeyLastState = false;
    private static boolean gKeyLastState = false;
    private static boolean f6KeyLastState = false;
    private static boolean rKeyLastState = false;

    @Override
    public void onInitializeClient() {
        LOGGER.info("Initializing Divine Client v4.0.0 (Unified High-Performance Fabric Mod)...");
        CONFIG = new DivineConfig();

        // 1. Initial IPC bridge check
        DivineIpcBridge.update(CONFIG);

        // 2. Start hardware polling & tick thread
        startHardwareEventPolling();

        LOGGER.info("Divine Client initialized successfully with all QoL features active.");
    }

    private void startHardwareEventPolling() {
        Thread thread = new Thread(() -> {
            Method glfwGetKeyMethod = null;
            Method glfwGetMouseButtonMethod = null;
            try {
                Class<?> glfwClass = Class.forName("org.lwjgl.glfw.GLFW");
                glfwGetKeyMethod = glfwClass.getMethod("glfwGetKey", long.class, int.class);
                glfwGetMouseButtonMethod = glfwClass.getMethod("glfwGetMouseButton", long.class, int.class);
            } catch (Exception e) {
                LOGGER.fine("GLFW not directly available in classloader: " + e.getMessage());
            }

            while (true) {
                try {
                    Thread.sleep(16); // ~60 ticks/s

                    // Sync state with IPC bridge
                    DivineIpcBridge.update(CONFIG);

                    // Update tick features
                    if (minecraftInstance != null) {
                        MovementFeatures.onClientTick(minecraftInstance, CONFIG);
                        RenderFeatures.updateFullbright(minecraftInstance, CONFIG);
                    }

                    // Poll GLFW if window handle is accessible
                    long windowHandle = getWindowHandle();
                    if (windowHandle != 0L && glfwGetKeyMethod != null) {
                        // Right Shift / M key -> Toggle Mod Menu
                        int rShiftState = (int) glfwGetKeyMethod.invoke(null, windowHandle, GLFW_KEY_RIGHT_SHIFT);
                        int mState = (int) glfwGetKeyMethod.invoke(null, windowHandle, GLFW_KEY_M);

                        boolean rShiftDown = (rShiftState == 1);
                        boolean mDown = (mState == 1);

                        if ((rShiftDown && !rShiftLastState) || (mDown && !mKeyLastState)) {
                            // Check if in game (not in a chat box or container)
                            if (DivineModMenuScreen.isOpen) {
                                DivineModMenuScreen.close();
                            } else {
                                DivineModMenuScreen.open(minecraftInstance, null, CONFIG);
                            }
                        }
                        rShiftLastState = rShiftDown;
                        mKeyLastState = mDown;

                        // G / F6 key -> Toggle Fullbright
                        int gState = (int) glfwGetKeyMethod.invoke(null, windowHandle, GLFW_KEY_G);
                        int f6State = (int) glfwGetKeyMethod.invoke(null, windowHandle, GLFW_KEY_F6);
                        boolean gDown = (gState == 1);
                        boolean f6Down = (f6State == 1);

                        if ((gDown && !gKeyLastState) || (f6Down && !f6KeyLastState)) {
                            CONFIG.toggleMod("fullbright");
                        }
                        gKeyLastState = gDown;
                        f6KeyLastState = f6Down;

                        // C key -> Smooth Zoom
                        int cState = (int) glfwGetKeyMethod.invoke(null, windowHandle, GLFW_KEY_C);
                        RenderFeatures.isZooming = (cState == 1);

                        // R key -> Toggle Sprint
                        int rState = (int) glfwGetKeyMethod.invoke(null, windowHandle, GLFW_KEY_R);
                        boolean rDown = (rState == 1);
                        if (rDown && !rKeyLastState) {
                            CONFIG.toggleMod("toggle_sprint");
                        }
                        rKeyLastState = rDown;

                        // Poll Keystrokes states
                        DivineHudRenderer.keyW = ((int) glfwGetKeyMethod.invoke(null, windowHandle, 87) == 1); // W
                        DivineHudRenderer.keyA = ((int) glfwGetKeyMethod.invoke(null, windowHandle, 65) == 1); // A
                        DivineHudRenderer.keyS = ((int) glfwGetKeyMethod.invoke(null, windowHandle, 83) == 1); // S
                        DivineHudRenderer.keyD = ((int) glfwGetKeyMethod.invoke(null, windowHandle, 68) == 1); // D
                        DivineHudRenderer.keySpace = ((int) glfwGetKeyMethod.invoke(null, windowHandle, 32) == 1); // Space

                        if (glfwGetMouseButtonMethod != null) {
                            DivineHudRenderer.keyLmb = ((int) glfwGetMouseButtonMethod.invoke(null, windowHandle, 0) == 1);
                            DivineHudRenderer.keyRmb = ((int) glfwGetMouseButtonMethod.invoke(null, windowHandle, 1) == 1);
                        }
                    }
                } catch (Throwable ignored) {}
            }
        }, "DivineClient-Hardware-Poller");
        thread.setDaemon(true);
        thread.start();
    }

    private static long getWindowHandle() {
        if (minecraftInstance == null) {
            try {
                Class<?> mcCls = Class.forName("net.minecraft.client.MinecraftClient");
                Method getInstance = mcCls.getMethod("getInstance");
                minecraftInstance = getInstance.invoke(null);
            } catch (Exception e) {
                try {
                    Class<?> mcCls = Class.forName("net.minecraft.class_310");
                    Method getInstance = mcCls.getMethod("method_1551");
                    minecraftInstance = getInstance.invoke(null);
                } catch (Exception ignored) {}
            }
        }

        if (minecraftInstance != null) {
            try {
                Field winField = minecraftInstance.getClass().getDeclaredField("window");
                winField.setAccessible(true);
                Object win = winField.get(minecraftInstance);
                if (win == null) {
                    Field f = minecraftInstance.getClass().getDeclaredField("field_1704");
                    f.setAccessible(true);
                    win = f.get(minecraftInstance);
                }
                if (win != null) {
                    Method getHandle = win.getClass().getMethod("getHandle");
                    return (Long) getHandle.invoke(win);
                }
            } catch (Exception ignored) {}
        }
        return 0L;
    }
}
