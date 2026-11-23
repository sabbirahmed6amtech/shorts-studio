# Shorts Studio

Turn long videos into YouTube Shorts on your own computer. Paste a YouTube link (or upload a file), and it:

1. downloads the video,
2. transcribes it locally with Whisper (word-level timestamps),
3. asks Gemini (free tier) to pick the best clips and write a title, description and hashtags for each,
4. opens an editor where you adjust clips on a waveform timeline, drag-select new ones, and position a 9:16 crop box,
5. renders each clip as a 1080×1920 video with word-by-word captions,
6. uploads it to YouTube, either right away or scheduled. YouTube publishes scheduled Shorts itself, so your computer doesn't need to be on at that time.

## Setup

You need:

| | Windows | Mac |
|---|---|---|
| Python 3.11 or 3.12 | [python.org](https://www.python.org/downloads/) (tick "Add Python to PATH") or `winget install Python.Python.3.12` | `brew install python@3.12` |
| ffmpeg | `winget install Gyan.FFmpeg` | `brew install ffmpeg-full` (the plain `ffmpeg` formula can't burn captions) |
| A JavaScript runtime, for YouTube links | `winget install DenoLand.Deno` or Node.js | `brew install deno` or Node.js |

If [uv](https://docs.astral.sh/uv/) is installed, the start script uses it and fetches the right Python by itself.

## Run

- **Windows:** double-click `start.bat`
- **Mac / Linux:** `./start.sh`

The first run installs packages (a few minutes). The app then opens at <http://127.0.0.1:8000>. The home page lists anything still missing from setup.

Add your Gemini API key in **Settings** (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)). Without a key you can still pick clips by hand. On the free tier Google may use what you send to improve its models.

## Connecting YouTube (one time, about 10 minutes)

Settings → YouTube channel walks you through it:

1. Create a project in [Google Cloud](https://console.cloud.google.com/projectcreate) and enable the **YouTube Data API v3**.
2. In **Google Auth Platform**, choose audience **External** and add your Google account as a **test user**.
3. Under **Clients**, create a **Desktop app** client and download its JSON file.
4. Upload the JSON in Settings, then press **Connect YouTube**.

Google rules to know:

- **Sign-in lasts 7 days while the app is in Testing.** Press **Publish app** on the Audience page to stay signed in. Google then shows an "unverified app" warning when you connect: choose *Advanced → Go to app*.
- **Uploads stay private until Google audits your project.** Until then, scheduled Shorts won't go public. Apply with the [YouTube API audit form](https://support.google.com/youtube/contact/yt_api_form).
- **About 6 uploads a day** on the default API quota.

## Captions

Settings → Captions sets the font, size, colours, words per screen and height. Three fonts are included (Anton, Poppins ExtraBold, Bebas Neue, all under the SIL Open Font License, see `fonts/`). Changing the caption style marks existing renders as out of date. Press **Render all** to update them.

## Where things live

Everything is in `data/`: the database (`app.db`), each video's files (`jobs/<id>/`, rendered Shorts in `jobs/<id>/clips/`), downloaded Whisper models (`models/`), and your YouTube sign-in (`youtube_token.json`; keep it private). Delete a video from the home page to free its space. Delete the whole `data/` folder to start fresh.

To use a different port: `PORT=8080 ./start.sh` (Mac) or `set PORT=8080` then `start.bat` (Windows).
