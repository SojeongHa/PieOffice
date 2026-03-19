# iOS Shortcut: Wake Mac + Open Terminal

## Prerequisites

- Mac and iPhone on the same WiFi network
- Mac "Wake for network access" enabled:
  System Settings > Battery > Options > "Wake for network access"
- Mac's MAC address (run `ifconfig en0 | grep ether` on Mac)
- Pie Office terminal set up (`./scripts/setup-terminal.sh`)

## Create the Shortcut

1. Open **Shortcuts** app on iPhone
2. Tap **+** to create new shortcut
3. Name it: "Mac Terminal"

### Actions:

**Action 1: Wake on LAN**
- Search for "Wake on LAN" in the Shortcuts Gallery
- Set MAC address to your Mac's address
- Set Broadcast address to 255.255.255.255

**Action 2: Wait**
- Add "Wait" action
- Set to **90 seconds**

**Action 3: Open URL**
- Add "Open URLs" action
- URL: `https://<mac-ip>:10317/terminal`
  - Replace `<mac-ip>` with your Mac's LAN IP

### Add to Home Screen:
- Tap share icon > "Add to Home Screen"
- One tap: wake Mac > wait > open terminal

## Tips

- Save the auth token in iPhone Notes or iCloud Keychain
- On first HTTPS visit, Safari will warn about self-signed cert
  - Tap "Advanced" > "Proceed"
- Token is saved in browser localStorage after first login
- If Mac's IP changes, update the shortcut URL
