# Getting started

A ten-minute tour for a new user: install, first launch, connect the apps you use, put a sound on a
key, change the language.

## 1. Install

* **Windows:** download the installer from [Releases](../../../releases), run it, done. A tray icon
  appears and the configuration window opens.
* **macOS / Linux, or from source:** see *Building from source* in the [README](../README.md).
  Run `open-loupedeck --web 127.0.0.1:8765` and open that address in a browser.

Plug in your **Loupedeck Live / Live S**. An **Elgato Stream Deck** works too (experimental, quit
the Elgato software first, see [streamdeck.md](streamdeck.md)). No device at hand? Pick
*Virtual 15 / Mega / Mini* under Services > General > Hardware, or run `open-loupedeck --web --virtual`
([virtual-device.md](virtual-device.md)): the deck is drawn in your browser and you can click its keys.

## 2. First launch: pick a pack

The first time, a welcome card offers starter packs: **Streamer** (OBS scenes, mic mute, live status,
a clock), **Music** (Spotify), **Smart home** (Home Assistant lights), **World of Warcraft**
([wow.md](wow.md)) or **Blank**. A pack is fitted to your device (keys that do not fit are dropped, with
a note). Nothing is final: change anything, or press **Undo** in the top bar to take the pack back in
one step. Everything saves as you type.

The picture on the left is your device. Click a key, a knob or a round button: the panel on the right
asks, in three steps, *what it does*, *how it looks*, and (for buttons) *which colour its light has*.
A key shows its real final look as soon as you pick an action. The pages (Main, Page 2...) are the
tabs above the deck; the round buttons of a Live S open pages 1 to 4.

"Applies to: This page / Every page" says whether what you change is for the page you are looking at
or for all pages. A control a page does not set itself simply shows the setting for every page: the
panel then shows what is inherited, with **Override on this page** to make it different here.

## 3. Connect OBS, Spotify, Twitch

Open the **Services** tab (or use the status chips at the top and the *Next steps* card under the deck).

* **OBS Studio:** in OBS open *Tools > WebSocket Server Settings*, enable the server and copy the
  password. In Services > OBS enter the address (default `127.0.0.1`, port `4455`) and the password.
  The OBS chip turns green; scene and mute keys now work.
* **Spotify:** press **Connect**, sign in in your browser and accept. You need Spotify Premium and a
  Spotify app open on some device.
* **Twitch:** press **Connect**, log in on the page that opens and approve. Several accounts can be added.
* **Home Assistant:** enter its address and a long-lived access token (Profile > Security).

You can use your own Spotify / Twitch application instead of the built-in one, see
[configuration.md](configuration.md#connecting-twitch-and-spotify-and-using-your-own-app).

## 4. Put a sound on a key

1. Click an empty key. In the action list choose **Play sound file**.
2. Press **Add sounds...** in the picker, or drop audio files (mp3, wav...) anywhere on the picker. You
   can also drop audio files straight onto an empty key of the deck: each file makes a sound key.
3. Pick the sound, set the volume if you like, press the preview button to hear it on this PC.

The key takes the sound's name and an icon on its own; change either under Appearance.
Sounds play on the computer that runs Open-Loupedeck.

## 5. Languages

English and French are built in. Services > Language: *Automatic* follows your system, or pick one.
It applies immediately, including the default key labels (text you typed yourself is never
translated). To add a language, see [translating.md](translating.md).

## Where next

* [configuration.md](configuration.md): every setting and action, for scripting the config file.
* [devices-features.md](devices-features.md) and [devices.md](devices.md): how devices are modelled.
* Something wrong? Services > General has the config folder and backups; the log level is in
  Services > Logging.
