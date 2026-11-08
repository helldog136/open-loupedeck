# World of Warcraft with open-loupedeck

open-loupedeck does three things for WoW, and nothing more:

1. **A key sends one key chord** to the game (`WoW macro / keybind` action).
2. **WoW icons** on your keys (the *WoW* tab of the icon picker, or any icon name you paste).
3. **A starter pack** with ten ready-made keys (offered on first launch, or paste the same keys yourself).

The macros themselves **stay in WoW**. You bind a macro (or a spell, an item, a mount...) to a rarely used key chord
inside the game, and a deck key sends that chord.

## The one-input-one-action rule

Blizzard forbids one input from triggering several actions. So one press on the deck sends **exactly one key chord**,
once: no sequences, no repeats, no timers. The `wow.keybind` action is deliberately separate from
`keyboard.play_sequence`, which can send several chords and should not be used for WoW. If you want something that
does several things, build it as a macro in WoW within the game's own rules, and bind that macro to one chord.

## Set it up

### 1. Pick the chord

Use chords you never press yourself, so nothing else in WoW or Windows reacts to them. The recommended ones are
**Ctrl+Shift+F13 to Ctrl+Shift+F22** (the starter pack uses exactly these, in order). F1 to F24 are supported, with
any mix of Ctrl, Alt and Shift. A chord is modifiers plus **exactly one** other key, for example `ctrl+shift+f13`.

Your keyboard probably has no F13 to F24 keys; that does not matter, the deck sends them. In the inspector you type the
chord (or click *Record* and press a combination that your keyboard can produce).

### 2. Bind a macro to it in WoW

1. In WoW, create the macro (`/macro`) and drag it onto an action bar slot. A spare slot, for example on a bar you
   have hidden, works well.
2. Open *Game Menu > Options > Keybindings* (the exact path and names vary slightly between WoW versions) and find that
   slot's binding (for example *Action Bar 5 Button 1* or *Action Button 7*).
3. Click the binding and **press the deck key** that sends your chord (open-loupedeck must be running and the key
   configured). WoW records the chord as if you had typed it. Save.

Alternative with `/click`: keep one macro on a bar button, bind the chord to that button as above, and let other macros
call it with `/click <ButtonName>` if you need to reuse it. The deck still sends only the one chord.

### 3. Configure the deck key

Pick the action **World of Warcraft > WoW macro / keybind**, type the chord in *Key chord*, and give the key a
*Macro name* (it is only shown on the key). Choose an icon in the **WoW** tab of the icon picker.

## Limits and things to know

- The chord is sent with ordinary simulated key presses to whichever window has focus. WoW must run as a **normal
  (non-admin) process**, like open-loupedeck; Windows does not let a normal process type into an elevated one.
- The key is held for a few milliseconds (modifiers first, key last, released in reverse), because games read the keyboard
  once per frame.
- Function keys **F13 to F24** are real virtual keys on Windows (`VK_F13` to `VK_F24`) and on Linux. On macOS only up to
  F20 exist; F21 to F24 give an error message in the log instead of sending anything.
- The Windows key, AltGr and multi-key chords are refused. Fix the chord in the inspector (it tells you what is wrong).
- If WoW does not accept an F13 to F24 chord in its binding screen, use another rare chord such as `ctrl+alt+shift+f9`
  or `ctrl+alt+shift+1`.

## Icons

WoW icons are Blizzard's artwork, so **open-loupedeck never bundles them**. An icon is written `wow:<icon_name>` and is
downloaded on demand from Wowhead's CDN (`https://wow.zamimg.com/images/wow/icons/large/<icon_name>.jpg`).

- A downloaded icon is stored in the icon cache folder (`%LOCALAPPDATA%\open-loupedeck\icons\wow\<icon_name>.jpg` on
  Windows) and is **never downloaded again**. Once cached, it also works offline.
- If a download fails (typo in the name, 404, no network) the failure is remembered for **one hour** so the server is not
  asked again on every redraw; the key simply shows no icon meanwhile.
- At most four downloads run at once, with timeouts and the generic user agent `open-loupedeck`.
- Above about 5000 cached icons the oldest ones are deleted.
- *Services > General > Clear WoW icon cache* deletes the downloaded icons (and forgets failures). They come back on
  demand.
- The picker's WoW tab searches a bundled list of icon **names** (names only, grouped by class, professions, mounts,
  consumables, items, misc). The thumbnails you see there are loaded from the CDN too, and show two letters when offline.

### Finding the name of any icon

Open the spell, item or achievement on [Wowhead](https://www.wowhead.com). Right-click its icon and copy the image
address. It looks like `https://wow.zamimg.com/images/wow/icons/large/inv_misc_rune_01.jpg`; the name is the file name
without `.jpg`: **`inv_misc_rune_01`**. Paste the name (or the whole link) in the *Any other icon* field of the WoW tab.
Names are lower-case letters, digits and underscores; the stored value is `wow:inv_misc_rune_01`.

open-loupedeck is not affiliated with or endorsed by Blizzard Entertainment or Wowhead. World of Warcraft is a trademark of
Blizzard Entertainment, Inc.
