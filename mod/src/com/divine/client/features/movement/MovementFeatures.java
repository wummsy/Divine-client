package com.divine.client.features.movement;

import com.divine.client.config.DivineConfig;

import java.lang.reflect.Field;
import java.lang.reflect.Method;

public class MovementFeatures {
    public static boolean isSprintActive = false;

    public static void onClientTick(Object client, DivineConfig config) {
        if (config == null || !config.toggle_sprint_enabled || client == null) return;
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
                Method setSprinting = player.getClass().getMethod("setSprinting", boolean.class);
                setSprinting.invoke(player, true);
                isSprintActive = true;
            }
        } catch (Throwable ignored) {}
    }
}
