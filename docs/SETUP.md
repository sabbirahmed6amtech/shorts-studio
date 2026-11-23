# Setup guide

Step-by-step setup for Windows and Mac. The [README](../README.md) has the short version;
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) covers what to do when a step fails.

1. [Install the tools](#1-install-the-tools)
2. [Get the app and start it](#2-get-the-app-and-start-it)
3. [Add a Gemini API key](#3-add-a-gemini-api-key)
4. [Connect YouTube](#4-connect-youtube)
5. [Connect Facebook (optional)](#5-connect-facebook-optional)
6. [Make transcription fast](#6-make-transcription-fast)
7. [Check everything works](#7-check-everything-works)

---

## 1. Install the tools

You need Python, ffmpeg and a JavaScript runtime. uv is optional but makes setup faster
and picks the right Python for you.

### Windows

Open **PowerShell** or **Terminal** and run:

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install DenoLand.Deno
winget install astral-sh.uv        # optional
```

Then **close and reopen** the terminal (and restart the app if it was open) so Windows
picks up the new commands. Check that they work:

```powershell
python --version      # 3.11 or 3.12
ffmpeg -version
deno --version        # or: node --version
```

Without winget, install Python from [python.org](https://www.python.org/downloads/) and
tick **Add Python to PATH** on the first installer screen. Then install ffmpeg from
[gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (the "full" or "essentials" build) and add its
`bin` folder to PATH, or point the app at it in Settings → Advanced.

### Mac

Install [Homebrew](https://brew.sh) if you don't have it, then:

```bash
brew install python@3.12
brew install ffmpeg-full
brew install deno
brew install uv          # optional
```

**Use `ffmpeg-full`, not `ffmpeg`.** Homebrew's plain `ffmpeg` has no caption support,
so rendering would fail. `ffmpeg-full` installs alongside any existing ffmpeg without
replacing it, and the app finds it automatically.

macOS ships an old Python 3.9 as `python3`, which is too old. The start script looks for
3.12 or 3.11 first, or lets uv fetch one.

### Linux

Install Python 3.11+, an ffmpeg build with libass (most distro packages have it), and
Deno or Node.js with your package manager, then use `./start.sh`.

### Why each tool is needed

| Tool | Used for |
|---|---|
| Python 3.11–3.12 | The app itself. 3.13 usually works too; 3.9 is too old |
| ffmpeg + ffprobe | Reading videos, extracting audio, rendering clips. The build needs libass (captions) and libx264 (H.264) |
| Deno or Node.js | yt-dlp needs a JavaScript runtime to download from YouTube. Uploads work without it |
| uv (optional) | Faster installs, and it downloads the right Python automatically |

---

## 2. Get the app and start it

Clone or copy the project folder anywhere, for example:

```bash
git clone https://github.com/sabbirahmed6amtech/shorts-studio.git
cd shorts-studio
```

Start it:

- **Windows:** double-click `start.bat` (or run it from a terminal to see messages).
- **Mac / Linux:** `./start.sh` from a terminal in the folder.

The first run:

1. creates `.venv/` (a private Python environment, using uv if available),
2. installs the packages in `requirements.txt` (a few minutes; faster-whisper and the
   Google libraries are the big ones),
3. starts the server on **http://127.0.0.1:8000** and opens your browser.

Later runs skip straight to step 3, unless `requirements.txt` changed (for example after
`git pull`), in which case packages are reinstalled.

Leave the terminal window open. Closing it, or pressing Ctrl+C, stops the app. Jobs
that were running resume on the next start.

**Setup checks:** the Videos page lists anything missing:

| Check | If it fails |
|---|---|
| ffmpeg and ffprobe | Nothing can be processed. Install ffmpeg, or set its folder in Settings → Advanced |
| ffmpeg can burn captions | Rendering fails while captions or hook titles are on. Install a full ffmpeg build |
| JavaScript runtime | YouTube links may fail. Install Deno or Node.js |
| Gemini API key | You can still pick clips by hand or use another AI |
| YouTube channel connected | You can still render and download clips |

---

## 3. Add a Gemini API key

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and sign in.
2. Create an API key and copy it.
3. In the app: **Settings → Gemini → API key**, paste, and press **Save settings**.

The default model is `gemini-3.8-flash`, with `gemini-3.5-flash-lite` as the backup.
Both were on Google's free tier when this was written. If Google renames models and you
see "model not found", put the current name from Google's
[model list](https://ai.google.dev/gemini-api/docs/models) into Settings.

On the free tier Google may use what you send to improve its products. The app sends
only text: transcript, video title, and loudness and chat markers.

---

## 4. Connect YouTube

This is a one-time setup of about 10 minutes. You create your own small Google Cloud
"app" that's allowed to upload to your channel.

### 4.1 Create the Google Cloud project

1. Open [console.cloud.google.com/projectcreate](https://console.cloud.google.com/projectcreate),
   name it (e.g. "Shorts Studio") and create it.
2. Enable the **YouTube Data API v3** for it:
   [console.cloud.google.com/apis/library/youtube.googleapis.com](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
   → **Enable**.

### 4.2 Set up sign-in (Google Auth Platform)

1. Open [console.cloud.google.com/auth/overview](https://console.cloud.google.com/auth/overview)
   and press **Get started**.
2. Enter an app name and your email. For **Audience**, choose **External**.
3. Under **Audience → Test users**, add the Google account that owns your YouTube channel.

### 4.3 Create the OAuth client

1. Open [console.cloud.google.com/auth/clients](https://console.cloud.google.com/auth/clients)
   → **Create client**.
2. Application type: **Desktop app**. Any name works.
3. Press **Download JSON** for the new client.

A *Desktop app* client works with any local address, so you don't need to register a
redirect URL.

### 4.4 Connect in the app

1. **Settings → YouTube channel → Upload client file**, and choose the JSON you
   downloaded.
2. Press **Connect YouTube**. Google's sign-in opens; choose the channel's account.
3. Google warns that the app isn't verified. It's your own app: choose **Advanced → Go to
   (app name)**, then allow the permissions.
4. You're sent back to Settings, which shows your channel name.

### 4.5 Two Google rules you'll want to deal with

- **The sign-in expires after 7 days while the app is in Testing.** To stay signed in, open
  **Audience** and press **Publish app**. That changes the status to "In production",
  with no review needed for your own use. You'll keep seeing the unverified warning when
  connecting, which is fine.
- **Uploads stay private until Google audits your project.** Every video uploaded through
  the API by an unaudited project is locked to private, so scheduled Shorts won't go
  public. Apply with the
  [YouTube API audit form](https://support.google.com/youtube/contact/yt_api_form). Until
  it's approved, you can still upload and then make videos public by hand in YouTube
  Studio, or render and **Download** clips and upload them yourself.

**Quota:** the default YouTube API quota is 10,000 units a day, and each upload costs
1,600, so about **6 uploads a day**. It resets at midnight Pacific time. You can request
more quota in Google Cloud.

---

## 5. Connect Facebook (optional)

This lets the app post the same clips as Reels on a Facebook Page that you manage.

### 5.1 Create the Meta app

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps) → **Create
   app**.
2. Choose the use case for **managing a Page** (the wording changes over time; pick the
   one that mentions Pages or content management).
3. Make sure the app can request these permissions: **`pages_show_list`**,
   **`pages_read_engagement`**, **`pages_manage_posts`**.
4. In **App settings → Basic**, copy the **App ID** and **App Secret**.

### 5.2 Get a token

1. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. Select your app at the top right.
3. Add the three permissions above.
4. Press **Generate Access Token**, log in, and **select your Page** when asked.
5. Copy the token.

### 5.3 Connect in the app

**Settings → Facebook Page**: paste the App ID, App Secret and token, then press
**Connect**. The app swaps the short-lived token for a long-lived one and fetches a token
for each Page you can post to. Page tokens made this way don't expire. If you manage
several Pages, choose one from the list.

### 5.4 Facebook rules

- Reels must be **3–90 seconds**. Longer clips skip Facebook, and the app tells you so.
- Scheduling works **10 minutes to 29 days** ahead.
- About **30 Reels a day** through the API.
- If posted Reels don't show up for other people, switch the app from **Development** to
  **Live** mode in the Meta app dashboard (it may ask for a privacy policy URL).

---

## 6. Make transcription fast

Transcription is the slowest step only when Whisper runs. In order of impact:

1. **Settings → Transcript source → Auto** (the default). Most YouTube videos have
   captions, which arrive in seconds.
2. **Faster Whisper** (on by default). About twice as fast, slightly less accurate.
3. **A smaller model:** `base` or `tiny` are much faster than `small`, with lower
   accuracy.
4. **Use the GPU:**
   - **Mac (Apple Silicon):** Settings → Run on → **Apple GPU (experimental)**.
   - **Windows/Linux with NVIDIA:** Settings → Run on → **NVIDIA GPU**. This needs NVIDIA's
     CUDA 12 runtime libraries (cuBLAS and cuDNN 9) installed and on PATH. If they're
     missing, the job fails with a CUDA or cuDNN error; switch back to CPU.

Gameplay with no talking doesn't need a transcript: choose **No transcript** and keep
**Loudness hints** on.

---

## 7. Check everything works

A quick test:

1. Paste a short YouTube video with talking (a few minutes long).
2. It should reach **Ready** in well under a minute with Auto transcript.
3. Open the editor. You should see Gemini's clips on the waveform, with titles.
4. Select a clip, press **Render**, and play the preview: captions, hook banner, 9:16.
5. If YouTube is connected, **Schedule** a clip for tomorrow and check that it appears in
   YouTube Studio as scheduled. (It stays private until your project is audited.)

If any step fails, look it up in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
