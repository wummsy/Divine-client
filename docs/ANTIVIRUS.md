Antivirus and Windows Defender Configuration

Divine Client runs local processes for Minecraft instances and dedicated server relays.
If Windows Defender flags Java memory operations or tunnel binaries, add the client folder to exclusions:

powershell -ExecutionPolicy Bypass -File tools/defender_exclusions.ps1
