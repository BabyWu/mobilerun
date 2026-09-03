# Example App Card Template

## Overview
Brief description of the app's purpose and main features.

Example:
- Feature 1
- Feature 2
- Feature 3

## Package Information
- Package name: `com.example.app`
- Main activity: `com.example.app.MainActivity`

## Navigation Structure

### Main Screen
Describe the main screen layout:
- Top bar / App bar
- Bottom navigation
- Main content area

### Key Screens
List important screens and how to reach them:
- Screen A: From main → tap X → select Y
- Screen B: From main → swipe right → tap Z

## Common Operations

### Login
1. Open app
2. Tap login button
3. Enter credentials
4. Tap submit

### Send Message
1. Navigate to messages
2. Tap compose button
3. Enter message text
4. Tap send

## Important Rules

**Timing:**
- Login takes 2-3 seconds
- List loading may take 1-2 seconds
- Real-time updates appear after 0.5s

**Accessibility:**
- All buttons have contentDescription
- Text fields have proper labels
- Use semantic actions over coordinates

**Edge Cases:**
- Network required for login
- Some features disabled in demo mode
- Offline mode has limited functionality

**Testing Tips:**
- Always start from home screen
- Use test account credentials
- Clear app state between tests if needed
