# Dream Show App Card

## Overview
Dream Show is a live streaming and video chat social application that allows users to watch live broadcasts, interact with streamers, send gifts, and engage in 1v1 video calls.

Main features:
- Live streaming (watch and broadcast)
- 1v1 video chat
- Gift system and virtual currency
- Social features (follow, messaging, footprint)
- Rank and level system
- VIP/Noble membership
- Fan groups and guard system

## Package Information
- Package name: `com.dream.like` (official/Google)
- Package name (Lite): `com.dream.like.lite`
- Namespace: `com.show.dd`
- Main application: `com.show.dd.MainApplication`
- Launch activity: `com.show.dd.ui.SplashActivity`

## Navigation Structure

### App Launch Flow
1. **SplashActivity** (Launch screen with ad)
   - Shows splash screen with optional advertisement
   - Checks login status
   - Redirects to LoginActivity or MainActivity

2. **LoginActivity** (Login screen)
   - Phone number + SMS code login
   - Facebook login
   - Google login
   - Navigate to: PhoneSMSActivity, FillProfileActivity

3. **MainActivity** (Main screen)
   - Bottom navigation with 5 tabs:
     - Home (live streams)
     - Discover/Explore
     - Messages
     - Me (profile)
     - Video Chat (optional)

### Main Sections

#### Home Tab
Location: MainActivity → HomeFragment
Features:
- Live stream grid/list
- Country filter
- Follow filter
- Search functionality
- Tap live card → LivePlayActivity

Navigation:
- Tap search icon → SearchActivity
- Tap live thumbnail → LivePlayActivity
- Swipe to refresh live list

#### Live Streaming

**Watch Live (LivePlayActivity)**
- Main live viewing screen
- Gift sending panel
- Chat messages
- Anchor profile
- Guard/Noble badges
- Interactive features (red packet, turntable)

**Start Broadcasting (LivePushActivity)**
- Camera preview
- Beauty filters (FaceUnity/ByteDance)
- Live settings
- Viewer list
- Gift notifications

#### Messages Tab
Location: MainActivity → Messages
Features:
- Chat list with recent conversations
- Official notifications
- System messages
- Tap conversation → ChatActivity

**ChatActivity** operations:
- Send text messages
- Send images
- Send voice messages
- Send gifts
- View user profile

#### Me Tab (Profile)
Location: MainActivity → Me section
Main options:
- User profile → UserInfoActivity
- Wallet → WalletActivity (diamonds, beans)
- Level → MyLevelActivity
- VIP → VipActivity
- Store → StoreActivity (decorations)
- Settings → SettingActivity

**Profile editing:**
1. Me → Profile avatar/name
2. Opens UserInfoActivity
3. Tap edit → UserInfoEditActivity
4. Edit name/bio → EditNameBioActivity

**Wallet operations:**
1. Me → Wallet
2. WalletActivity shows balance
3. Charge/recharge → payment flow
4. View records → ChargeRecordActivity

**Settings path:**
1. Me → Settings icon (top-right)
2. SettingActivity with options:
   - Account security → AccountSecurityActivity
   - Blacklist → BlacklistActivity
   - Notification settings → NotificationSettingActivity
   - Account related → AccountsRelatedActivity
   - About → AboutActivity
   - Logout

#### Video Chat
- VideoChatActivity: 1v1 video call screen
- VideoChatSettingActivity: call settings
- Ring/CallEvent: incoming call notifications

### Special Features

**Guard System**
- GuardRankActivity: guard leaderboard
- MyGuardkActivity: my guards list
- Guard badge in live rooms

**Noble System**
- NobleActivity: noble privilege overview
- NobleRankActivity: noble rankings
- NobleUpgrade: level up notifications

**Fan Groups**
- FansGroupActivity: fan group management
- Fan badges and exclusive features

**Medals & Titles**
- MyMedalActivity: medal collection
- MyTitleActivity: title management
- MedalDetailActivity: medal details
- MedalTitleManagerActivity: title equipment

**Rank System**
- RankActivity: various leaderboards
- Anchor rank
- Wealth rank
- Charm rank

**Red Packet & Turntable**
- RedPackActivity: red packet details
- RedPackageRainActivity: red packet rain game
- TurntableActivity: lucky wheel game

## Common Operations

### Login
1. Launch app → SplashActivity
2. If not logged in → LoginActivity
3. Choose login method:
   - Phone: Enter number → PhoneSMSActivity → SMS code
   - Facebook: Tap Facebook button → OAuth flow
   - Google: Tap Google button → OAuth flow
4. First time: FillProfileActivity (set profile)
5. Success → MainActivity

### Watch Live Stream
1. MainActivity → Home tab
2. Browse live grid
3. Tap live thumbnail
4. LivePlayActivity opens
5. Can send gifts, chat, follow anchor

### Start Broadcasting
1. MainActivity → Home tab (or center button)
2. Tap start live button
3. LivePushActivity with camera preview
4. Apply beauty filters
5. Tap "Go Live" button
6. Broadcasting starts

### Send Gift in Live Room
1. In LivePlayActivity
2. Tap gift icon (bottom panel)
3. Gift panel slides up
4. Select gift
5. Choose quantity
6. Confirm send
7. Gift animation plays

### Video Chat (1v1)
1. Navigate to target user profile
2. Tap video call button
3. Ring notification sent
4. If accepted → VideoChatActivity
5. Video call starts

### Recharge Diamonds
1. MainActivity → Me tab
2. Tap Wallet
3. WalletActivity opens
4. Tap recharge button
5. Select package
6. Google Play billing flow
7. Purchase confirmation

### Edit Profile
1. MainActivity → Me tab
2. Tap profile area (avatar/name)
3. UserInfoActivity opens
4. Tap edit button
5. UserInfoEditActivity opens
6. Change avatar, name, bio, gender, birthday
7. Save changes

### Search Users/Lives
1. MainActivity → Home tab
2. Tap search icon (top-right)
3. SearchActivity opens
4. Enter keywords
5. View results (users/live rooms)
6. Tap result → profile or live room

## Important Rules

**Login & Authentication:**
- App requires login to access most features
- Multiple login methods: phone, Facebook, Google
- Session managed via JWT tokens
- Auto-logout on token expiration

**Permissions:**
- Camera: required for broadcasting and video chat
- Microphone: required for broadcasting and video chat
- Storage: required for uploading photos/videos
- Notifications: for chat and live notifications

**Network Requirements:**
- App requires stable internet connection
- Live streaming needs good bandwidth (upload >1Mbps)
- Video chat needs low latency connection

**Timing:**
- Splash screen: 2-3 seconds
- Login SMS: 1-2 seconds to send
- Live stream loading: 1-3 seconds
- Gift animation: 2-5 seconds
- Video call connection: 2-4 seconds

**Accessibility:**
- Most buttons have contentDescription
- Text fields properly labeled
- Use semantic actions when possible
- Screen reader compatible (partial)

**OEM Differences:**
- Camera/mic permissions vary by device
- Some beauty filters may not work on low-end devices
- Notification handling differs by Android version
- Picture-in-picture support varies

**Testing Tips:**
- Always start from home screen or SplashActivity
- Use test accounts with sufficient balance
- Check network connectivity before live tests
- Clear app data between full test runs
- Mock payment in test environment
- Some features require specific user roles (anchor/audience)
- Live room features only work in active live sessions

**Known Limitations:**
- Beauty filters need decent device performance
- Live streaming quality depends on network
- Some regions may have restricted features
- Age verification required for certain features

**Security:**
- Credentials stored securely
- Payment via Google Play billing
- HTTPS for all network requests
- Firebase authentication integration
