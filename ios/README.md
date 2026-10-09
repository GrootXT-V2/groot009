# Kurama for iPhone 🦊

A real iPhone app: Kurama sleeps curled up in a corner, wakes up when you tap it,
talks with you, wanders around, and walks back to bed — the same fox and routine
as on your Mac. There's also a home-screen / lock-screen widget (tap it to talk).

The app talks to Groot running on your Mac (`python -m groot --phone`) for its
brain, memory and voice.

## Install it on your iPhone (one time, about 20 minutes)

You need a Mac with **Xcode** (free in the App Store) and your **Apple ID**.

1. Install the tools (in Terminal):
   ```bash
   brew install xcodegen
   ```
2. Make the Xcode project and open it:
   ```bash
   cd groot009/ios
   xcodegen
   open Kurama.xcodeproj
   ```
3. In Xcode, click **Kurama** (blue icon, top left) → **Signing & Capabilities**:
   - Tick **Automatically manage signing**, set **Team** to your Apple ID
     ("Add an Account…" if it isn't there).
   - Do the same for the **KuramaWidget** target.
   - If Xcode says the bundle identifier is taken, change `com.groot009.kurama`
     to something unique, like `com.yourname.kurama` (and `.widget` for the widget).
4. Plug in your iPhone with a cable, unlock it, and tap **Trust**.
   Turn on **Settings → Privacy & Security → Developer Mode** (the iPhone restarts).
5. Pick your iPhone at the top of Xcode and press **▶ Run**.
6. First launch on the iPhone: **Settings → General → VPN & Device Management** →
   tap your Apple ID → **Trust**. Then open Kurama.

With a free Apple ID, the app stops opening after **7 days** — just press ▶ Run in
Xcode again. A paid Apple Developer account ($99/year) makes it last a year.

## Connect it to your Mac

1. On your Mac: `python -m groot --phone`
2. Scan the **"iPhone app (Kurama)"** QR code with the iPhone camera → **Open in Kurama**.
3. Tap the fox (or 🎤) and talk. Allow the microphone and speech recognition when asked.

The Wi-Fi QR code works at home. For use anywhere, install `cloudflared`
(`brew install cloudflared`) and scan the "iPhone app, anywhere" QR code instead.

## Add the widget

Long-press the home screen → **+** (top left) → search **Kurama** → pick a size → **Add Widget**.
Tap it to open Kurama and start talking.

## What iPhones don't allow

Apple doesn't let any app walk on top of other apps or listen for "Hey Kurama" in the
background, so Kurama lives in its own app (and widget) and you tap it to wake it up.
