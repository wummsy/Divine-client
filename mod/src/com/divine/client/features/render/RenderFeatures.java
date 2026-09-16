package com.divine.client.features.render;

import com.divine.client.config.DivineConfig;

import java.lang.reflect.Field;
import java.lang.reflect.Method;

public class RenderFeatures {
    public static boolean isZooming = false;
    public static double currentFovModifier = 1.0;
    private static double originalGamma = 1.0;
    private static boolean gammaSaved = false;

    public static void updateFullbright(Object client, DivineConfig config) {
        if (client == null || config == null) return;
        try {
            Field optionsField = client.getClass().getDeclaredField("options");
            optionsField.setAccessible(true);
            Object options = optionsField.get(client);
            if (options == null) {
                Field f = client.getClass().getDeclaredField("field_1690");
                f.setAccessible(true);
                options = f.get(client);
            }
            if (options != null) {
                Field gammaField = null;
                for (Field f : options.getClass().getDeclaredFields()) {
                    if (f.getName().equals("gamma") || f.getName().equals("field_1840")) {
                        gammaField = f;
                        break;
                    }
                }
                if (gammaField != null) {
                    gammaField.setAccessible(true);
                    Object gammaObj = gammaField.get(options);
                    if (gammaObj instanceof Number) {
                        if (!gammaSaved) {
                            originalGamma = ((Number) gammaObj).doubleValue();
                            gammaSaved = true;
                        }
                        if (config.fullbright_enabled) {
                            gammaField.set(options, 16.0);
                        } else {
                            gammaField.set(options, originalGamma);
                        }
                    } else if (gammaObj != null) {
                        // SimpleOption in 1.19+
                        Method setValue = null;
                        for (Method m : gammaObj.getClass().getMethods()) {
                            if (m.getName().equals("setValue") || m.getName().equals("method_41748")) {
                                setValue = m;
                                break;
                            }
                        }
                        if (setValue != null) {
                            setValue.invoke(gammaObj, config.fullbright_enabled ? 16.0 : originalGamma);
                        }
                    }
                }
            }
        } catch (Throwable ignored) {}
    }

    public static double getFovModifier(DivineConfig config) {
        if (config != null && config.zoom_enabled && isZooming) {
            // Smooth zoom target: 0.3
            currentFovModifier += (0.3 - currentFovModifier) * 0.35;
        } else {
            // Smooth zoom release: 1.0
            currentFovModifier += (1.0 - currentFovModifier) * 0.35;
        }
        return currentFovModifier;
    }
}
