# 🛠️ Troubleshooting & FAQ

Frequently asked questions and solutions to common technical issues.

---

## ❓ Frequently Asked Questions

### Q: Minecraft crashes on startup or will not launch.
**A**: Ensure you have a valid Java 21 runtime installed. In Divine Client, click **Fix Java** in the launcher settings or launch error banner to automatically repair your Java runtime.

### Q: Why do I not see my Discord cosmetics in-game?
**A**: Make sure you have authorized your account by clicking **Authorize with Discord** in the launcher and running `/link code:XXXX` with DivineBot.

### Q: How do I change allocated RAM?
**A**: Open the Divine Client launcher, click the **Settings (⚙️)** icon, and adjust the **Memory Allocation (RAM)** slider. Recommended: `4096 MB` (4 GB) or `6144 MB` (6 GB).

### Q: Where are game logs located?
**A**: Whenever you launch an instance, the launcher automatically displays the live **Game Output Console**. You can also find raw logs in `.divineclient/instances/<instance_name>/logs/latest.log`.

---

## 🔍 Diagnostic Checklist

1. **Verify Java Version**: Must be OpenJDK 21 (Adoptium Temurin recommended).
2. **Check Mod Compatibility**: Divine Client is built natively for Fabric 1.21.11.
3. **Graphics Drivers**: Ensure your GPU drivers (NVIDIA, AMD, or Intel) are up-to-date with Vulkan/OpenGL 4.5 support.
