# Android Settings App Card

## Overview
Android Settings app provides system configuration and device information.

Common package names:
- `com.android.settings` (most devices)
- `com.android.se` (some OEMs)

## Main Sections

### Top Level
- Network & internet (WiFi, Mobile data, Hotspot)
- Connected devices (Bluetooth, Pairing)
- Apps (App management, Permissions)
- Display (Brightness, Screen timeout)
- Sound (Volume, Ringtone)
- Storage (Internal/External storage)
- Security (Screen lock, Encryption)
- Accounts (Google, Corporate)
- About phone (Model, Android version, Build)

### Navigation
- Main screen uses RecyclerView with preference items
- Each section may have subsections
- Back button returns to previous level
- Search icon in top-right for quick access

## Common Operations

### Open Settings
From any screen:
1. Press home button
2. Open app drawer
3. Find and tap "Settings" icon

Or use:
- Quick settings tile (swipe down twice)
- Long-press home for Google Assistant > "open settings"

### Navigate to Section
Pattern:
1. Open Settings
2. Scroll to find section title
3. Tap section
4. Navigate subsections as needed

### About Phone
Location: Settings → About phone (bottom of main list)
Shows:
- Device name
- Phone number
- Android version
- Security patch
- Build number

## Important Rules

**Accessibility:**
- Prefer text labels over coordinates
- Most items have contentDescription
- Use scroll action for long lists

**OEM Differences:**
- Samsung: "Settings" with different UI
- Xiaomi: "Settings" with MIUI customization
- Stock Android: cleanest hierarchy

**Speed:**
- Settings app is usually instant to open
- Some sections (Storage, Battery) may take 1-2s to load data
- About phone loads immediately

**Testing Tips:**
- Always press home before starting
- Use back button to return to previous screen
- Don't assume fixed item positions (list order may vary)
