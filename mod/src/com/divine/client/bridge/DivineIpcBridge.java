package com.divine.client.bridge;

import com.divine.client.config.DivineConfig;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.logging.Logger;

public class DivineIpcBridge {
    private static final Logger LOGGER = Logger.getLogger("DivineIpcBridge");
    private static final String BRIDGE_URL = "http://127.0.0.1:10230/api/ingame/state";
    private static boolean isConnected = false;
    private static long lastCheck = 0;

    public static void update(DivineConfig config) {
        long now = System.currentTimeMillis();
        if (now - lastCheck < 5000) return; // check every 5 seconds
        lastCheck = now;

        new Thread(() -> {
            try {
                URL url = new URL(BRIDGE_URL);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("GET");
                conn.setConnectTimeout(800);
                conn.setReadTimeout(800);

                int code = conn.getResponseCode();
                if (code == 200) {
                    try (BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()))) {
                        StringBuilder sb = new StringBuilder();
                        String line;
                        while ((line = reader.readLine()) != null) {
                            sb.append(line);
                        }
                        String response = sb.toString();
                        isConnected = true;
                        config.server_status = "Connected to Divine Services";
                        // If response contains unlocked cloaks or settings, apply
                        if (response.contains("booster") || response.contains("BOOSTER2026")) {
                            config.unlocked_cloaks.add("booster");
                        }
                    }
                } else {
                    isConnected = false;
                    config.server_status = "cant connect to server";
                }
            } catch (Exception e) {
                isConnected = false;
                config.server_status = "cant connect to server";
            }
        }, "divine-ipc-bridge").start();
    }

    public static boolean isConnected() {
        return isConnected;
    }
}
