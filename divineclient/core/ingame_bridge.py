"""In-Game Client Mod Bridge, Mod Configuration, Cosmetics & Player Verification.

Manages:
  1. Built-in In-Game QoL Mods configuration (FPS, Coordinates, Zoom, Gamma, Low Fire, Small Totem,
     Scoreboard Customizer, Block Overlay, Armor Warning, Chat Tweaks, Memory HUD, Attack Cooldown, Item Counter).
  2. Cosmetics Closet (Cloaks, Wings, Halos, Auras, Badges) linked to the user's Divine/Discord profile.
  3. Dynamic Promo Code Generation & Verification Engine (linked to Discord /generatecode).
  4. Divine Network Verified Player Database & Nametag Badge lookup.
  5. In-game friends list sync with Divine account verification enforcement.
"""
import json
import os
import time
import secrets
import logging
from .. import paths

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(paths.DATA_DIR, "ingame_mods.json")
COSMETICS_FILE = os.path.join(paths.DATA_DIR, "cosmetics.json")
REDEEMED_FILE = os.path.join(paths.DATA_DIR, "redeemed_codes.json")
GENERATED_CODES_FILE = os.path.join(paths.DATA_DIR, "generated_codes.json")

# Default QoL Mods catalog
DEFAULT_MODS_CONFIG = {
    "fps_display": {
        "id": "fps_display",
        "name": "FPS Display",
        "category": "hud",
        "description": "Displays smooth real-time framerate counter with customizable colors and styling.",
        "icon": "speed",
        "enabled": True,
        "options": {
            "position": "top-left",
            "show_label": True,
            "prefix": "FPS: ",
            "text_color": "#ffffff",
            "background": True,
            "font_shadow": True,
            "scale": 1.0
        }
    },
    "coordinates": {
        "id": "coordinates",
        "name": "Coordinates",
        "category": "hud",
        "description": "Clean XYZ coordinate HUD showing biome, compass direction, and Nether conversion.",
        "icon": "navigation",
        "enabled": True,
        "options": {
            "position": "top-left",
            "show_biome": True,
            "show_direction": True,
            "show_nether": False,
            "layout": "vertical",
            "text_color": "#ffffff",
            "background": True
        }
    },
    "cinematic_zoom": {
        "id": "cinematic_zoom",
        "name": "Cinematic Zoom",
        "category": "qol",
        "description": "Smooth cinematic magnification with mouse scroll wheel zoom.",
        "icon": "search",
        "enabled": True,
        "options": {
            "keybind": "C",
            "zoom_factor": 4.0,
            "smooth_animation": True,
            "scroll_zoom": True,
            "hide_hand": True,
            "cinematic_camera": False
        }
    },
    "fullbright_gamma": {
        "id": "fullbright_gamma",
        "name": "Fullbright / Gamma",
        "category": "visuals",
        "description": "Instantly brightens caves and nighttime without torch lighting or potion particles.",
        "icon": "brightness",
        "enabled": True,
        "options": {
            "keybind": "G",
            "gamma_boost": 1000,
            "mode": "gamma",
            "instant_toggle": True
        }
    },
    "low_fire": {
        "id": "low_fire",
        "name": "Low Fire",
        "category": "pvp",
        "description": "Lowers first-person burning fire screen overlay height for unobstructed vision during PvP combat.",
        "icon": "flame",
        "enabled": True,
        "options": {
            "fire_height": 30,
            "transparent_particles": True,
            "blue_soul_fire": False
        }
    },
    "small_totem": {
        "id": "small_totem",
        "name": "Small Totem",
        "category": "pvp",
        "description": "Reduces held Totem of Undying scale and suppresses intrusive full-screen pop-up animation.",
        "icon": "totem",
        "enabled": True,
        "options": {
            "totem_scale": 0.5,
            "disable_popup_animation": True,
            "mute_activation_sound": False,
            "compact_offhand": True
        }
    },
    "scoreboard_customizer": {
        "id": "scoreboard_customizer",
        "name": "Scoreboard Customizer",
        "category": "visuals",
        "description": "Hide red score numbers, adjust background opacity, and remove border clutter.",
        "icon": "scoreboard",
        "enabled": True,
        "options": {
            "hide_red_numbers": True,
            "borderless": True,
            "background_opacity": 0.4,
            "position": "top-right",
            "hide_scoreboard": False
        }
    },
    "block_overlay": {
        "id": "block_overlay",
        "name": "Block Overlay & Outline",
        "category": "visuals",
        "description": "Custom block selection box outlines, fill color with alpha, and smooth outline rendering.",
        "icon": "cube",
        "enabled": True,
        "options": {
            "outline_color": "#ffffff",
            "fill_color": "rgba(255,255,255,0.12)",
            "line_thickness": 2.0,
            "chroma": False
        }
    },
    "armor_warning": {
        "id": "armor_warning",
        "name": "Armor Low Durability Alert",
        "category": "hud",
        "description": "Visual and audio alert on HUD when any armor piece durability falls below 15%.",
        "icon": "shield",
        "enabled": True,
        "options": {
            "warning_threshold": 15,
            "flash_screen": True,
            "sound_alert": True,
            "position": "center"
        }
    },
    "chat_tweaks": {
        "id": "chat_tweaks",
        "name": "Chat Tweaks & Anti-Spam",
        "category": "qol",
        "description": "Compact duplicate messages [x3], transparent background, unlimited chat history, and copy text.",
        "icon": "chat",
        "enabled": True,
        "options": {
            "compact_spam": True,
            "transparent_box": True,
            "chat_shadow": True,
            "infinite_scroll": True
        }
    },
    "memory_hud": {
        "id": "memory_hud",
        "name": "Memory & RAM HUD",
        "category": "hud",
        "description": "Real-time Java heap allocation, GC cycles, and system RAM monitor.",
        "icon": "memory",
        "enabled": True,
        "options": {
            "position": "top-right",
            "show_percentage": True,
            "show_graph": False
        }
    },
    "attack_cooldown": {
        "id": "attack_cooldown",
        "name": "Attack Indicator / Hit Delay",
        "category": "pvp",
        "description": "Weapon cooldown recharge indicator rendered beside crosshair or on hotbar.",
        "icon": "sword",
        "enabled": True,
        "options": {
            "indicator_style": "crosshair",
            "show_percent": True
        }
    },
    "item_counter": {
        "id": "item_counter",
        "name": "Item Counter HUD",
        "category": "hud",
        "description": "Live inventory count for Totems of Undying, Golden Apples, Ender Pearls, and Arrows on your HUD.",
        "icon": "bag",
        "enabled": True,
        "options": {
            "track_totems": True,
            "track_gapples": True,
            "track_arrows": True,
            "track_pearls": True,
            "position": "bottom-center"
        }
    },
    "nick_hider": {
        "id": "nick_hider",
        "name": "Nick Hider",
        "category": "qol",
        "description": "Hides your IGN and skin in-game, in tab list, and in chat for streamer privacy.",
        "icon": "masks",
        "enabled": False,
        "options": {
            "fake_name": "You",
            "hide_own_name": True,
            "hide_other_nicks": False,
            "hide_own_skin": False
        }
    },
    "particle_changer": {
        "id": "particle_changer",
        "name": "Particle Changer",
        "category": "visuals",
        "description": "Multiply critical hit sparks, enchant particles, and customize sharp textures.",
        "icon": "particles",
        "enabled": True,
        "options": {
            "crit_multiplier": 2.5,
            "sharp_particles": True,
            "custom_color": "#ffffff",
            "always_crit_particles": False
        }
    },
    "uhc_overlay": {
        "id": "uhc_overlay",
        "name": "UHC Overlay",
        "category": "pvp",
        "description": "Enlarges Golden Apple & player health render indicators with absorption glow.",
        "icon": "shield",
        "enabled": True,
        "options": {
            "golden_apple_glow": True,
            "player_health_hud": True,
            "absorption_indicator": True,
            "pot_counter": True
        }
    },
    "keystrokes": {
        "id": "keystrokes",
        "name": "Keystrokes HUD",
        "category": "hud",
        "description": "WASD keys, Spacebar, Left/Right Mouse CPS counters with dynamic press lighting.",
        "icon": "keyboard",
        "enabled": True,
        "options": {
            "position": "bottom-right",
            "show_cps": True,
            "show_mouse": True,
            "show_space": True,
            "chroma": False,
            "text_color": "#ffffff",
            "background_color": "rgba(0,0,0,0.5)"
        }
    },
    "armor_status": {
        "id": "armor_status",
        "name": "Armor Status",
        "category": "hud",
        "description": "Displays equipped helmet, chestplate, leggings, boots, and main/off-hand durability.",
        "icon": "shield_half",
        "enabled": True,
        "options": {
            "position": "bottom-right",
            "show_durability_percent": True,
            "show_damage_val": False,
            "show_item_counts": True,
            "direction": "vertical"
        }
    },
    "potion_effects": {
        "id": "potion_effects",
        "name": "Potion Status",
        "category": "hud",
        "description": "Active potion status HUD with animated timers and expiring warning flashes.",
        "icon": "flask",
        "enabled": True,
        "options": {
            "position": "top-right",
            "compact_view": False,
            "blink_expiring": True,
            "hide_vanilla_hud": True
        }
    },
    "crosshair_customizer": {
        "id": "crosshair_customizer",
        "name": "Crosshair Customizer",
        "category": "visuals",
        "description": "Custom crosshair shapes (circle, plus, dot, arrow, T-shape) with custom colors.",
        "icon": "crosshair",
        "enabled": False,
        "options": {
            "style": "plus",
            "color": "#ffffff",
            "center_dot": True,
            "thickness": 2,
            "size": 8,
            "dynamic_spread": False
        }
    },
    "toggle_sprint": {
        "id": "toggle_sprint",
        "name": "Toggle Sprint & Sneak",
        "category": "qol",
        "description": "One-key toggle for continuous sprinting and sneaking with on-screen status text.",
        "icon": "run",
        "enabled": True,
        "options": {
            "hud_indicator": True,
            "indicator_position": "bottom-left",
            "sprint_toggle": True,
            "sneak_toggle": False,
            "custom_text": "[Sprinting (Toggled)]"
        }
    },
    "ping_display": {
        "id": "ping_display",
        "name": "Ping & TPS Monitor",
        "category": "hud",
        "description": "Real-time network latency (ms) and server tickrate (TPS) HUD indicator.",
        "icon": "wifi",
        "enabled": True,
        "options": {
            "position": "top-left",
            "show_tps": True,
            "color_coded": True
        }
    },
    "motion_blur": {
        "id": "motion_blur",
        "name": "Motion Blur",
        "category": "visuals",
        "description": "Cinematic camera velocity blur for buttery smooth high refresh rate visuals.",
        "icon": "blur",
        "enabled": False,
        "options": {
            "intensity": 35,
            "disable_in_gui": True
        }
    },
    "time_changer": {
        "id": "time_changer",
        "name": "Time Changer",
        "category": "visuals",
        "description": "Locks client-side sky and world time to Day, Sunset, Night, or Midnight.",
        "icon": "sun",
        "enabled": False,
        "options": {
            "mode": "day",
            "custom_ticks": 6000
        }
    },
    "reach_display": {
        "id": "reach_display",
        "name": "Reach Display",
        "category": "pvp",
        "description": "Measures and renders exact attack distance in blocks on player hits.",
        "icon": "target",
        "enabled": True,
        "options": {
            "position": "top-center",
            "precision": 2,
            "fade_duration_ms": 1500
        }
    },
    "combo_counter": {
        "id": "combo_counter",
        "name": "Combo Counter",
        "category": "pvp",
        "description": "Counts consecutive PvP melee hits with customizable sound alerts and combo milestones.",
        "icon": "sword",
        "enabled": True,
        "options": {
            "position": "top-center",
            "reset_timeout_ms": 2000,
            "text_color": "#ffffff"
        }
    },
    "freelook": {
        "id": "freelook",
        "name": "Freelook 360",
        "category": "qol",
        "description": "360-degree free perspective camera rotation without turning your character body.",
        "icon": "eye",
        "enabled": True,
        "options": {
            "keybind": "Left Alt",
            "invert_y": False,
            "smooth_camera": True
        }
    },
    "item_physics": {
        "id": "item_physics",
        "name": "Item Physics 3D",
        "category": "visuals",
        "description": "Realistic 3D ground item rotation, tossing physics, and floating water buoyancy.",
        "icon": "cube",
        "enabled": True,
        "options": {
            "rotation_speed": 1.0,
            "realistic_gravity": True
        }
    },
    "divine_nametags": {
        "id": "divine_nametags",
        "name": "Divine Nametag Badges",
        "category": "visuals",
        "description": "Renders official pure white Divine Sun emblems next to player names in-game.",
        "icon": "badge",
        "enabled": True,
        "options": {
            "show_badge": True,
            "badge_style": "sun_white",
            "show_on_self": True,
            "show_on_friends": True,
            "show_on_all_divine_users": True,
            "badge_scale": 1.0
        }
    }
}

# Master Catalog of Available Cosmetics
COSMETICS_CATALOG = {
    "cloaks": [
        {
            "id": "cloak_divine_obsidian",
            "name": "Divine Obsidian Cloak",
            "rarity": "Legendary",
            "preview_color": "#090a0f",
            "description": "Official Divine Client dark obsidian fabric emblazoned with the glowing white sun crest.",
            "unlocked": False,
            "tag": "OFFICIAL"
        },
        {
            "id": "cloak_solaris_white",
            "name": "Solaris Radiant White Cloak",
            "rarity": "Epic",
            "preview_color": "#ffffff",
            "description": "Pure brilliant white cloak emitting celestial light rays.",
            "unlocked": False,
            "tag": "POPULAR"
        },
        {
            "id": "cloak_nebula_cosmic",
            "name": "Nebula Galaxy Cloak",
            "rarity": "Epic",
            "preview_color": "#7c3aed",
            "description": "Deep interstellar cosmos texture with slowly drifting star clusters.",
            "unlocked": False,
            "tag": "COSMIC"
        },
        {
            "id": "cloak_emerald_dragon",
            "name": "Emerald Wyvern Cloak",
            "rarity": "Rare",
            "preview_color": "#10b981",
            "description": "Shimmering jade dragon scales woven into heavy battle cloak.",
            "unlocked": False,
            "tag": "STORE"
        },
        {
            "id": "cloak_crimson_void",
            "name": "Crimson Void Cloak",
            "rarity": "Rare",
            "preview_color": "#ef4444",
            "description": "Abyssal red gradient with crackling dark flame edges.",
            "unlocked": False,
            "tag": "PVP"
        },
        {
            "id": "cloak_discord_booster",
            "name": "Discord Booster Cloak",
            "rarity": "Exclusive",
            "preview_color": "#5865f2",
            "description": "Unlocked via Level 3 Discord Server Boosters.",
            "unlocked": False,
            "tag": "PROMO: BOOSTER"
        },
        {
            "id": "cloak_2026_anniversary",
            "name": "Divine 2026 Anniversary Cloak",
            "rarity": "Mythic",
            "preview_color": "#38bdf8",
            "description": "Celebratory 2026 limited edition cloak with gilded sun embroidery.",
            "unlocked": False,
            "tag": "PROMO: DIVINE2026"
        }
    ],
    "wings": [
        {
            "id": "wings_divine_archangel",
            "name": "Divine Archangel Wings",
            "rarity": "Mythic",
            "description": "Majestic pure white feathered wings with animated flapping physics.",
            "unlocked": False,
            "tag": "PROMO: DEVINE"
        },
        {
            "id": "wings_cosmic_butterfly",
            "name": "Cosmic Prismatic Wings",
            "rarity": "Epic",
            "description": "Translucent glowing butterfly wings pulsing with celestial hue.",
            "unlocked": False,
            "tag": "PROMO: COSMIC"
        },
        {
            "id": "wings_dragon_glider",
            "name": "Ender Dragon Glider",
            "rarity": "Rare",
            "description": "Black draconic wings with purple membrane glow.",
            "unlocked": False,
            "tag": "DEFAULT"
        },
        {
            "id": "wings_demon_shadow",
            "name": "Demon Shadow Wings",
            "rarity": "Rare",
            "description": "Jagged dark fiend wings surrounded by crimson embers.",
            "unlocked": False,
            "tag": "STORE"
        }
    ],
    "halos": [
        {
            "id": "halo_luminous_divine",
            "name": "Luminous Divine Halo",
            "rarity": "Mythic",
            "description": "Hovering celestial gold ring radiating divine light above player head.",
            "unlocked": False,
            "tag": "PROMO: DEVINE"
        },
        {
            "id": "bandana_solar",
            "name": "Solaris White Bandana",
            "rarity": "Epic",
            "description": "Clean white silk forehead bandana tied in combat knot.",
            "unlocked": False,
            "tag": "POPULAR"
        },
        {
            "id": "crown_obsidian",
            "name": "Obsidian Spiked Crown",
            "rarity": "Exclusive",
            "description": "Gothic obsidian crown worn by guild masters.",
            "unlocked": False,
            "tag": "PROMO: BOOSTER"
        },
        {
            "id": "cat_ears_cyber",
            "name": "Cyber Tech Cat Ears",
            "rarity": "Rare",
            "description": "Futuristic neon head accessories.",
            "unlocked": False,
            "tag": "STORE"
        }
    ],
    "auras": [
        {
            "id": "aura_sun_sparks",
            "name": "Divine Sun Sparks",
            "rarity": "Epic",
            "description": "Orbiting golden light rays and floating micro-particles.",
            "unlocked": False,
            "tag": "OFFICIAL"
        },
        {
            "id": "aura_cosmic_stardust",
            "name": "Cosmic Star Dust",
            "rarity": "Epic",
            "description": "Glittering nebula stardust following player footsteps.",
            "unlocked": False,
            "tag": "PROMO: COSMIC"
        },
        {
            "id": "aura_frost_cryo",
            "name": "Cryo Frost Aura",
            "rarity": "Rare",
            "description": "Freezing subzero mist swirling around player boots.",
            "unlocked": False,
            "tag": "STORE"
        },
        {
            "id": "aura_flame_vortex",
            "name": "Flame Vortex",
            "rarity": "Rare",
            "description": "Blazing infernal fire rings.",
            "unlocked": False,
            "tag": "STORE"
        }
    ],
    "badges": [
        {
            "id": "badge_divine_sun_white",
            "name": "Divine Pure White Sun",
            "rarity": "Legendary",
            "description": "Official pure white Divine sun emblem rendered beside player username in-game.",
            "unlocked": False,
            "tag": "DEFAULT"
        },
        {
            "id": "badge_divine_sun_gold",
            "name": "Divine Radiant Gold Sun",
            "rarity": "Mythic",
            "description": "Gilded VIP sun emblem awarded to early adopters.",
            "unlocked": False,
            "tag": "PROMO: DIVINE2026"
        },
        {
            "id": "badge_creator",
            "name": "Verified Divine Creator",
            "rarity": "Exclusive",
            "description": "Special video creator badge beside in-game name.",
            "unlocked": False,
            "tag": "PROMO: STREAMER"
        },
        {
            "id": "badge_booster",
            "name": "Discord Server Booster",
            "rarity": "Exclusive",
            "description": "Shimmering purple booster gem displayed on nametags.",
            "unlocked": False,
            "tag": "PROMO: BOOSTER"
        }
    ]
}

# Standard Drops Registry
STANDARD_PROMO_CODES = {
    "DIVINE2026": {
        "title": "2026 Anniversary Pack",
        "description": "Unlocks Divine 2026 Anniversary Cloak, Radiant Gold Sun Nametag Badge, and 1,000 Divine Coins.",
        "unlocks": ["cloak_2026_anniversary", "badge_divine_sun_gold"]
    },
    "GAMMA": {
        "title": "Fullbright Ultra Preset",
        "description": "Unlocks Gamma Boost Ultra Preset and Cryo Frost Aura.",
        "unlocks": ["aura_frost_cryo"]
    },
    "COSMIC": {
        "title": "Cosmic Prismatic Wings Pack",
        "description": "Unlocks Cosmic Prismatic Butterfly Wings and Cosmic Star Dust Aura.",
        "unlocks": ["wings_cosmic_butterfly", "aura_cosmic_stardust"]
    },
    "DEVINE": {
        "title": "Divine Celestial Archangel Set",
        "description": "Unlocks Divine Archangel Wings and Luminous Divine Halo.",
        "unlocks": ["wings_divine_archangel", "halo_luminous_divine"]
    },
    "STREAMER": {
        "title": "Streamer & Creator Pack",
        "description": "Unlocks Verified Divine Creator Nametag Badge and Streamer Nick Hider Pro.",
        "unlocks": ["badge_creator"]
    },
    "BOOSTER": {
        "title": "Discord Server Booster Pack",
        "description": "Unlocks Discord Booster Cloak, Obsidian Spiked Crown, and Server Booster Badge.",
        "unlocks": ["cloak_discord_booster", "crown_obsidian", "badge_booster"]
    },
    "BOOSTER2026": {
        "title": "Divine 2026 Server Booster Celestial Pack",
        "description": "Unlocks Exclusive Divine Discord Booster Cloak, Obsidian Spiked Crown, and Server Booster Badge.",
        "unlocks": ["cloak_discord_booster", "crown_obsidian", "badge_booster"]
    }
}

# Verified Divine Network Player Registry (Database seed of known users)
VERIFIED_DIVINE_PLAYERS = {
    "DivinePlayer": {
        "username": "DivinePlayer",
        "verified": True,
        "badge": "badge_divine_sun_white",
        "badge_name": "Divine Pure White Sun",
        "badge_icon": "/assets/divine_icon.png",
        "discord_tag": "DivinePlayer#0001",
        "rank": "Divine Verified",
        "equipped_cloak": "cloak_divine_obsidian",
        "equipped_wings": None,
        "status": "online",
        "presence_detail": "PvP Practice with Low Fire & Small Totem"
    },
    "solarisdev": {
        "username": "SolarisDev",
        "verified": True,
        "badge": "badge_divine_sun_gold",
        "badge_name": "Divine Radiant Gold Sun",
        "badge_icon": "/assets/divine_icon.png",
        "discord_tag": "SolarisDev#1337",
        "rank": "Divine Lead",
        "equipped_cloak": "cloak_2026_anniversary",
        "equipped_wings": "wings_divine_archangel",
        "status": "online",
        "presence_detail": "Testing Divine Client v4.0.0"
    },
    "divineplayer": {
        "username": "DivinePlayer",
        "verified": True,
        "badge": "badge_divine_sun_white",
        "badge_name": "Divine Pure White Sun",
        "badge_icon": "/assets/divine_icon.png",
        "discord_tag": "DivinePlayer#2026",
        "rank": "Divine User",
        "equipped_cloak": "cloak_solaris_white",
        "equipped_wings": None,
        "status": "online",
        "presence_detail": "Exploring Survival World"
    },
    "gamma": {
        "username": "Gamma",
        "verified": True,
        "badge": "badge_divine_sun_white",
        "badge_name": "Divine Pure White Sun",
        "badge_icon": "/assets/divine_icon.png",
        "discord_tag": "Gamma#4040",
        "rank": "Divine User",
        "equipped_cloak": "cloak_nebula_cosmic",
        "equipped_wings": "wings_dragon_glider",
        "status": "online",
        "presence_detail": "In Main Menu"
    }
}


# -----------------------------------------------------------------------------
# DYNAMIC DISCORD /GENERATECODE ENGINE
# -----------------------------------------------------------------------------

def load_generated_codes():
    """Load persistent database of Discord-generated redeemable codes."""
    paths.ensure_dirs()
    if os.path.isfile(GENERATED_CODES_FILE):
        try:
            with open(GENERATED_CODES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_generated_codes(codes_dict):
    """Save generated codes database to disk."""
    paths.ensure_dirs()
    tmp = GENERATED_CODES_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(codes_dict, f, indent=2)
        os.replace(tmp, GENERATED_CODES_FILE)
        return True
    except Exception as e:
        logger.error("Could not save generated codes: %s", e)
        return False


def generate_promo_code(item_type, item_id, title=None, description=None, max_uses=1, creator="Discord /generatecode"):
    """Generate a new unique redeemable code for a specific item (used by Discord bot /generatecode)."""
    codes = load_generated_codes()
    
    # Generate random 16-character code e.g. DIVINE-ABCD-1234-EFGH
    prefix = "DIVINE"
    part1 = secrets.token_hex(2).upper()
    part2 = secrets.token_hex(2).upper()
    part3 = secrets.token_hex(2).upper()
    code_str = f"{prefix}-{part1}-{part2}-{part3}"

    item_name = item_id.replace("cloak_", "").replace("wings_", "").replace("halo_", "").replace("aura_", "").replace("badge_", "").replace("_", " ").title()
    if not title:
        title = f"{item_name} ({item_type.capitalize()})"
    if not description:
        description = f"Exclusive {item_type} generated via Discord command: {item_name}."

    code_data = {
        "code": code_str,
        "item_type": item_type,
        "item_id": item_id,
        "title": title,
        "description": description,
        "max_uses": int(max_uses),
        "used_count": 0,
        "redeemed_by": [],
        "created_at": time.time(),
        "creator": creator
    }

    codes[code_str] = code_data
    save_generated_codes(codes)
    return code_data


# -----------------------------------------------------------------------------
# MODS CONFIG & PERSISTENCE
# -----------------------------------------------------------------------------

def load_mods_config():
    """Load user in-game mods config from disk, merged with defaults."""
    paths.ensure_dirs()
    cfg = dict(DEFAULT_MODS_CONFIG)
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                # Clean up legacy removed mods
                saved.pop("hypixel_mods", None)
                saved.pop("hypixel_quickplay", None)
                for k, v in saved.items():
                    if k in cfg and isinstance(v, dict):
                        cfg[k] = {**cfg[k], **v}
                        if "options" in v and "options" in cfg[k]:
                            cfg[k]["options"] = {**cfg[k]["options"], **v["options"]}
        except Exception as e:
            logger.warning("Could not read in-game mods config: %s", e)
    return cfg


def save_mods_config(cfg):
    """Save in-game mods config to disk."""
    paths.ensure_dirs()
    tmp = CONFIG_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG_FILE)
        return True
    except Exception as e:
        logger.error("Could not save in-game mods config: %s", e)
        return False


def set_mod_state(mod_id, enabled=None, options=None):
    """Update single mod enabled state or options."""
    cfg = load_mods_config()
    if mod_id not in cfg:
        return None
    if enabled is not None:
        cfg[mod_id]["enabled"] = bool(enabled)
    if options and isinstance(options, dict):
        if "options" not in cfg[mod_id]:
            cfg[mod_id]["options"] = {}
        cfg[mod_id]["options"].update(options)
    save_mods_config(cfg)
    return cfg[mod_id]


# -----------------------------------------------------------------------------
# COSMETICS ENGINE & REDEMPTIONS
# -----------------------------------------------------------------------------

def load_cosmetics_state():
    """Load equipped cosmetics and unlocked items state."""
    paths.ensure_dirs()
    default_state = {
        "equipped": {
            "cloak": "cloak_divine_obsidian",
            "wings": None,
            "halo": "bandana_solar",
            "aura": "aura_sun_sparks",
            "badge": "badge_divine_sun_white"
        },
        "unlocked_items": [
            "cloak_divine_obsidian",
            "cloak_solaris_white",
            "cloak_nebula_cosmic",
            "cloak_emerald_dragon",
            "cloak_crimson_void",
            "wings_dragon_glider",
            "wings_demon_shadow",
            "bandana_solar",
            "cat_ears_cyber",
            "aura_sun_sparks",
            "aura_frost_cryo",
            "aura_flame_vortex",
            "badge_divine_sun_white"
        ]
    }
    if os.path.isfile(COSMETICS_FILE):
        try:
            with open(COSMETICS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                saved_eq = dict(saved.get("equipped", {}))
                # Remove legacy removed items
                if saved_eq.get("cloak") in ("cloak_hypixel_champion", "cape_hypixel_champion"):
                    saved_eq["cloak"] = "cloak_divine_obsidian"
                # Normalize legacy 'cape' key to 'cloak'
                if "cape" in saved_eq and "cloak" not in saved_eq:
                    val = saved_eq.pop("cape")
                    if val and val.startswith("cape_"):
                        val = val.replace("cape_", "cloak_")
                    saved_eq["cloak"] = val
                eq = {**default_state["equipped"], **saved_eq}
                saved_unlocked = [
                    (it.replace("cape_", "cloak_") if it.startswith("cape_") else it)
                    for it in saved.get("unlocked_items", [])
                    if it not in ("cloak_hypixel_champion", "cape_hypixel_champion")
                ]
                unlocked = list(set(default_state["unlocked_items"] + saved_unlocked))
                return {"equipped": eq, "unlocked_items": unlocked}
        except Exception as e:
            logger.warning("Could not read cosmetics state: %s", e)
    return default_state


def save_cosmetics_state(state):
    """Save cosmetics state to disk."""
    paths.ensure_dirs()
    tmp = COSMETICS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, COSMETICS_FILE)
        return True
    except Exception as e:
        logger.error("Could not save cosmetics state: %s", e)
        return False


def equip_cosmetic_item(slot, item_id):
    """Equip or unequip a cosmetic item in a slot."""
    state = load_cosmetics_state()
    slot_clean = (slot or "").lower().strip()
    if slot_clean == "cape":
        slot_clean = "cloak"
    
    valid_slots = ["cloak", "wings", "halo", "aura", "badge"]
    if slot_clean not in valid_slots:
        raise ValueError(f"Invalid cosmetic slot: {slot}")
    
    if item_id is None or item_id == "" or item_id == "none":
        state["equipped"][slot_clean] = None
    else:
        normalized_id = item_id.replace("cape_", "cloak_") if item_id.startswith("cape_") else item_id
        if normalized_id not in state["unlocked_items"] and item_id not in state["unlocked_items"]:
            raise ValueError(f"Cosmetic '{item_id}' is locked! Redeem a product code or visit the store.")
        state["equipped"][slot_clean] = normalized_id if normalized_id in state["unlocked_items"] else item_id

    save_cosmetics_state(state)
    return state


def load_redeemed_codes():
    """Load list of redeemed promo codes."""
    paths.ensure_dirs()
    if os.path.isfile(REDEEMED_FILE):
        try:
            with open(REDEEMED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_redeemed_codes(codes_list):
    """Save redeemed codes list to disk."""
    paths.ensure_dirs()
    tmp = REDEEMED_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(codes_list, f, indent=2)
        os.replace(tmp, REDEEMED_FILE)
        return True
    except Exception:
        return False


def redeem_promo_code(code_str, user_id=None):
    """Redeem a product code (standard drops OR Discord-generated /generatecode keys)."""
    code_clean = (code_str or "").strip().upper()
    if not code_clean:
        return {"success": False, "error": "Please enter a redeemable code."}

    user_identifier = str(user_id or "local_user")

    # 1. Check dynamic Discord generated codes database
    generated_pool = load_generated_codes()
    # Case-insensitive lookup
    matched_gen_key = None
    for k in generated_pool.keys():
        if k.upper() == code_clean:
            matched_gen_key = k
            break

    if matched_gen_key:
        gen_data = generated_pool[matched_gen_key]
        max_u = int(gen_data.get("max_uses", 1))
        used_u = int(gen_data.get("used_count", 0))
        redeemed_by = gen_data.get("redeemed_by", [])

        if user_identifier in redeemed_by:
            return {"success": False, "error": f"You have already claimed this Discord code ({code_clean})."}

        if max_u > 0 and used_u >= max_u:
            return {"success": False, "error": f"Code '{code_clean}' has already reached maximum uses ({max_u})."}

        # Grant cosmetic
        item_id = gen_data.get("item_id")
        slot = gen_data.get("item_type", "cloak")
        if slot == "cape":
            slot = "cloak"

        cosmetics_state = load_cosmetics_state()
        if item_id not in cosmetics_state["unlocked_items"]:
            cosmetics_state["unlocked_items"].append(item_id)
            if not cosmetics_state["equipped"].get(slot):
                cosmetics_state["equipped"][slot] = item_id

        save_cosmetics_state(cosmetics_state)

        # Update generated code usage
        gen_data["used_count"] = used_u + 1
        gen_data["redeemed_by"].append(user_identifier)
        generated_pool[matched_gen_key] = gen_data
        save_generated_codes(generated_pool)

        return {
            "success": True,
            "code": code_clean,
            "title": gen_data.get("title") or "Discord Reward Unlocked",
            "description": gen_data.get("description") or f"Unlocked item: {item_id}",
            "unlocked_items": [item_id],
            "cosmetics_state": cosmetics_state
        }

    # 2. Check standard official promo drops
    redeemed = load_redeemed_codes()
    if code_clean in [c.upper() for c in redeemed]:
        return {"success": False, "error": f"Code '{code_clean}' has already been redeemed on this Divine account."}
    if code_clean in STANDARD_PROMO_CODES:
        promo = STANDARD_PROMO_CODES[code_clean]
        cosmetics_state = load_cosmetics_state()
        unlocked_any = []

        for item_id in promo.get("unlocks", []):
            if item_id not in cosmetics_state["unlocked_items"]:
                cosmetics_state["unlocked_items"].append(item_id)
                unlocked_any.append(item_id)
                if (item_id.startswith("cloak_") or item_id.startswith("cape_")) and not cosmetics_state["equipped"].get("cloak"):
                    cosmetics_state["equipped"]["cloak"] = item_id
                elif item_id.startswith("wings_") and not cosmetics_state["equipped"].get("wings"):
                    cosmetics_state["equipped"]["wings"] = item_id
                elif item_id.startswith("halo_") and not cosmetics_state["equipped"].get("halo"):
                    cosmetics_state["equipped"]["halo"] = item_id
                elif item_id.startswith("badge_") and not cosmetics_state["equipped"].get("badge"):
                    cosmetics_state["equipped"]["badge"] = item_id

        save_cosmetics_state(cosmetics_state)
        redeemed.append(code_clean)
        save_redeemed_codes(redeemed)

        return {
            "success": True,
            "code": code_clean,
            "title": promo.get("title"),
            "description": promo.get("description"),
            "unlocked_items": promo.get("unlocks", []),
            "cosmetics_state": cosmetics_state
        }

    return {
        "success": False,
        "error": f"Invalid code '{code_clean}'. Check the Divine Discord server announcements or run /generatecode to create keys."
    }


def lookup_player_badge(username):
    """Look up whether a player is a verified Divine Client user and return their badge & cosmetics."""
    if not username:
        return {"verified": False, "username": username}

    key = username.strip().lower()

    # Check verified registry
    if key in VERIFIED_DIVINE_PLAYERS:
        player = VERIFIED_DIVINE_PLAYERS[key]
        return {
            "verified": True,
            "username": player["username"],
            "badge": player.get("badge", "badge_divine_sun_white"),
            "badge_name": player.get("badge_name", "Divine Pure White Sun"),
            "badge_icon": player.get("badge_icon", "/assets/divine_icon.png"),
            "discord_tag": player.get("discord_tag"),
            "rank": player.get("rank", "Divine User"),
            "equipped_cloak": player.get("equipped_cloak") or player.get("equipped_cape"),
            "equipped_wings": player.get("equipped_wings"),
            "status": player.get("status", "online"),
            "presence_detail": player.get("presence_detail", "Online in Divine Client")
        }

    # Check local database if server db is available
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from server import db as server_db
        conn = server_db.get_conn()
        row = conn.execute("SELECT * FROM users WHERE lower(username) = ?", (key,)).fetchone()
        if row:
            return {
                "verified": True,
                "username": row["username"],
                "badge": "badge_divine_sun_white",
                "badge_name": "Divine Pure White Sun",
                "badge_icon": "/assets/divine_icon.png",
                "discord_tag": f"{row['username']}#verified",
                "rank": "Divine User",
                "equipped_cloak": "cloak_divine_obsidian",
                "equipped_wings": None,
                "status": row["presence"] or "online",
                "presence_detail": row["presence_detail"] or "Online in Divine Client"
            }
    except Exception:
        pass

    return {
        "verified": False,
        "username": username,
        "badge": None,
        "rank": "Unregistered Player"
    }


def is_divine_account_linked(username):
    """Strict check to verify if a username has an active Divine Client account linked."""
    info = lookup_player_badge(username)
    return bool(info.get("verified"))


def get_full_catalog_with_status():
    """Return catalog of all cosmetics annotated with unlock and equip status."""
    state = load_cosmetics_state()
    catalog = dict(COSMETICS_CATALOG)
    result = {}
    for cat, items in catalog.items():
        result[cat] = []
        for it in items:
            it_copy = dict(it)
            it_copy["unlocked"] = it["id"] in state["unlocked_items"]
            slot_name = cat[:-1] if cat.endswith("s") else cat
            it_copy["equipped"] = (state["equipped"].get(slot_name) == it["id"])
            result[cat].append(it_copy)
    return {
        "categories": result,
        "equipped": state["equipped"],
        "unlocked_count": len(state["unlocked_items"])
    }


def sync_ingame_state(minecraft_username=None):
    """Compile complete real-time client state for the in-game HUD and mod engine."""
    mods_cfg = load_mods_config()
    cosmetics = get_full_catalog_with_status()
    badge_info = lookup_player_badge(minecraft_username or "DivinePlayer")
    
    return {
        "timestamp": time.time(),
        "client_version": "4.0.0",
        "mods": mods_cfg,
        "cosmetics": cosmetics,
        "player_badge": badge_info,
        "hud_layout": {
            "fps": {"x": 10, "y": 10},
            "coordinates": {"x": 10, "y": 30},
            "keystrokes": {"x": -160, "y": -140},
            "armor_status": {"x": -60, "y": -120},
            "potion_effects": {"x": -180, "y": 10},
            "toggle_sprint": {"x": 10, "y": -30},
            "divine_nametag": {"enabled": True, "show_badge": True}
        }
    }
