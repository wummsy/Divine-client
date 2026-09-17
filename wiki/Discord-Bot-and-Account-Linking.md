# 🤖 Discord Bot & Account Linking

Divine Client features tight integration with Discord via the official **DivineBot** and web services.

---

## 🔗 How to Link Your Account

1. Open the Divine Client launcher.
2. In the top navigation bar, click **Authorize with Discord** or navigate to your profile settings.
3. Your browser will open `https://divineclient.net/link?code=XXXXXX` (or your configured self-hosted instance).
4. Authorize via Discord OAuth2.
5. In Discord, you can verify your status with the slash command:
   ```
   /link code:XXXXXX
   ```
6. Your Minecraft username, unlocked cosmetics, and roles will instantly synchronize across the launcher and in-game client.

---

## 📋 DivineBot Slash Commands

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/link` | `code: <verification_code>` | Connect your Discord account to your Minecraft IGN. |
| `/unlink` | None | Disconnect your linked Minecraft account. |
| `/profile` | `[user: @member]` | View linked Minecraft profile, stats, cosmetics, and role perks. |
| `/cosmetics` | None | Open the interactive cosmetics inventory to equip capes, wings, and hats. |
| `/status` | None | Check Divine Client server, database, and auth status. |
| `/grant` | `user: @member, cosmetic_id: <id>` | *(Admin)* Grant exclusive cosmetic items or perks to a user. |
