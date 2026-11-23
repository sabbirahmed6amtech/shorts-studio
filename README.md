# Shorts Studio

Turn long videos into YouTube Shorts on your own computer. Paste a YouTube link (or upload a file), and it:

1. downloads the video,
2. gets a transcript: YouTube's own captions when available (seconds), or Whisper on your computer,
3. asks Gemini (free tier) to pick the best clips and write a title, hook title, description and hashtags for each. For streams and gameplay it also tells Gemini where the audio gets loud and, for past live streams, where the chat explodes,
4. opens an editor where you adjust clips on a waveform timeline, drag-select new ones, and position a 9:16 crop box,
5. renders each clip as a 1080×1920 video with word-by-word captions,
6. uploads it to YouTube and, optionally, to a Facebook Page as a Reel, right away or scheduled. Both platforms publish scheduled posts themselves, so your computer doesn't need to be on at that time.

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

## Using another AI instead of Gemini (optional)

If Gemini is out of free quota or overloaded, press **Use another AI** in the editor:

1. **Copy prompt** copies exactly what Gemini would get (transcript, loudness and chat markers, your clip settings) plus rules to reply with only JSON.
2. Paste it into ChatGPT, DeepSeek or any other AI, copy its reply, and paste it back.
3. **Import clips** reads the JSON (even if the AI adds text or code fences around it), applies the same checks as Gemini's answers, and replaces the AI clips you haven't edited.

Very long videos make long prompts; free versions of some AI tools may cut them off.

## Connecting Facebook (optional)

Settings → Facebook Page walks you through it: create an app at Meta for Developers with
`pages_show_list`, `pages_read_engagement` and `pages_manage_posts`, generate a token in
Graph API Explorer for your Page, and paste the App ID, App Secret and token. Limits: Reels
of 3–90 seconds, scheduled 10 minutes to 29 days ahead, about 30 API posts a day. If posts
don't show for other people, switch the app to Live mode.

## Live chat hints

For a past YouTube live stream with chat replay, the app downloads the chat, counts messages
per second and keeps a few sample messages (the raw file is deleted afterwards). Gemini then sees
markers like `(CHAT x6: "no way", "w")` next to the moments viewers reacted to. Turn it off in
Settings → Transcription.

## Hook title

Gemini writes a short banner for each clip ("He tried to get GTA 6 for free"), shown in a box for
the first few seconds. It's at the top for a single crop and on the line between the parts for
Streamer + content. Edit it per clip in the editor; style it in Settings → Captions.

## Captions

Settings → Captions sets the font, size, colours, words per screen and height. Three fonts are included (Anton, Poppins ExtraBold, Bebas Neue), plus Noto Sans Bengali, used automatically for Bengali words. All are under the SIL Open Font License; see `fonts/`. Changing the caption style marks existing renders as out of date. Press **Render all** to update them.

## Where things live

Everything is in `data/`: the database (`app.db`), each video's files (`jobs/<id>/`, rendered Shorts in `jobs/<id>/clips/`), downloaded Whisper models (`models/`), your YouTube sign-in (`youtube_token.json`) and Facebook Page tokens (`facebook.json`); keep both private. Delete a video from the home page to free its space. Delete the whole `data/` folder to start fresh.

To use a different port: `PORT=8080 ./start.sh` (Mac) or `set PORT=8080` then `start.bat` (Windows).
