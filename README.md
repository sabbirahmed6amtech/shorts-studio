# Shorts Studio

Turn long videos, streams and gameplay into vertical Shorts on your own computer, then post or
schedule them on YouTube and Facebook.

Paste a YouTube link or upload a file, and Shorts Studio:

1. **Downloads** the video.
2. **Gets a transcript:** YouTube's own captions when the video has them (seconds), or
   Whisper running on your computer.
3. **Finds the best moments.** Gemini (free tier) reads the transcript, plus markers for
   where the audio gets loud and, for past live streams, where the chat explodes. It
   suggests clips with a score, title, hook title, description and hashtags.
4. **Opens an editor** where you adjust clips on a waveform timeline, drag to create
   new ones, and frame the vertical video: one 9:16 crop, or the streamer camera on top
   with the game below.
5. **Renders** each clip as a 1080×1920 video with word-by-word captions and a hook
   banner for the first seconds.
6. **Posts** it to YouTube Shorts and, optionally, Facebook Reels, right away or
   scheduled. Both platforms publish scheduled posts themselves, so your computer can be
   off at that time.

Everything runs locally. The app lives in one folder, keeps its data in `data/`, and is
only reachable from your own computer (`127.0.0.1`).

---

## Contents

- [Quick start](#quick-start)
- [How to use it](#how-to-use-it)
- [Features in detail](#features-in-detail)
- [Settings reference](#settings-reference)
- [Where things live](#where-things-live)
- [Updating, moving and resetting](#updating-moving-and-resetting)
- [Privacy and limits](#privacy-and-limits)
- [Full setup guide](docs/SETUP.md) (YouTube, Facebook, Gemini, GPU)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

---

## Quick start

**1. Install the tools** (once per computer):

| What | Windows | Mac |
|---|---|---|
| Python 3.11 or 3.12 | `winget install Python.Python.3.12`, or [python.org](https://www.python.org/downloads/) with **Add Python to PATH** ticked | `brew install python@3.12` |
| ffmpeg (with caption support) | `winget install Gyan.FFmpeg` | `brew install ffmpeg-full` |
| JavaScript runtime (for YouTube links) | `winget install DenoLand.Deno` | `brew install deno` |
| *Optional:* uv (faster setup) | `winget install astral-sh.uv` | `brew install uv` |

On Mac, use `ffmpeg-full`: the plain `ffmpeg` formula can't burn captions. Node.js also
works as the JavaScript runtime if you already have it. After installing on Windows,
close and reopen any terminal windows so the new commands are found.

**2. Start the app:**

- **Windows:** double-click `start.bat`
- **Mac / Linux:** open Terminal in this folder and run `./start.sh`

The first run sets up a private Python environment in `.venv/` and installs packages,
which takes a few minutes. After that the app starts in seconds and opens
**http://127.0.0.1:8000** in your browser. Keep the terminal window open while you use
it; closing it stops the app.

**3. Finish setup in the app.** The home page shows **Setup checks**: anything missing
is listed with the fix. Then open **Settings** and:

- add a **Gemini API key** (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)),
- connect **YouTube** (one-time, about 10 minutes; see [docs/SETUP.md](docs/SETUP.md#4-connect-youtube)),
- optionally connect a **Facebook Page** ([docs/SETUP.md](docs/SETUP.md#5-connect-facebook-optional)).

You can try everything except posting without connecting any accounts.

---

## How to use it

### 1. Add a video

On the **Videos** page, paste a YouTube link or upload a file (`.mp4`, `.mov`, `.mkv`,
`.webm`, `.m4v`). The video then goes through these stages, with progress shown:

| Stage | What happens |
|---|---|
| Downloading | yt-dlp downloads up to 1080p, preferring H.264 so every browser can play it |
| Transcribing | YouTube captions, Whisper or nothing, depending on Settings; then the live chat replay for past streams |
| Gemini is picking clips | One request to Gemini; the result is cleaned up and saved as clips |
| Ready | Open the editor |

If something fails, the error is shown with **Retry**. If Gemini fails (no key, rate
limit, overloaded), the video still becomes Ready and you can pick clips by hand, press
**Run AI again**, or use **Use another AI**.

Closing the app mid-job is safe: on the next start it resumes where it stopped and skips
finished stages.

### 2. Edit clips

Open a Ready video with **Open editor**.

- **Timeline:** drag across the waveform to create a clip. Drag a clip to move it, or
  drag its edges to trim. Click a clip to select it. The **Zoom** slider helps on long
  videos. **+ Clip at playhead** adds a 30-second clip where the playhead is.
- **Clip list (right):** each clip shows time, length and score. Green means a high
  score, amber medium, grey low, and blue means you made it yourself. Badges show render
  and posting status.
- **Clip details:** start and end times (type them, or use **Start = playhead** and
  **End = playhead**), title, **hook title**, description and hashtags. Changes save by
  themselves. The panel also shows what's said in the clip and why Gemini picked it.
- **Space** plays or pauses (except while typing).

### 3. Frame the vertical video

Choose a **Layout** under the video:

- **Single crop:** a 9:16 box you drag sideways. It's set per clip.
- **Streamer + content:** a blue **Streamer** box over the facecam and an orange
  **Content** box over the game. Drag to move, and drag the corner to resize; each box
  keeps the right shape so nothing gets stretched. **Streamer height** sets how much of
  the Short the camera takes (25–60%). This is set once for the whole video, and new
  videos start from the last layout you used.

The **Preview** to the right of the video shows the final Short live.

### 4. Render

Press **Render** on a clip, or **Render all**. Each clip becomes a 1080×1920 MP4 with
captions and hook title, with a preview player and a **Download** button. If you change a
clip, its framing or the caption style after rendering, it shows **Edited since render**.
Render again, or just post it: posting re-renders automatically when needed.

### 5. Post or schedule

On a clip's panel:

- **YouTube:** pick a time and press **Schedule**, or **Upload now** as public, unlisted
  or private.
- **Facebook Reels:** pick a time and press **Schedule**, or **Post now**.

**Schedule all** (top of the clip list) posts every clip that isn't posted yet, best
score first, one per slot. Slots start at your default publish time and are spaced by
your chosen gap; it posts to the platforms turned on under Settings → Publishing.

The **Schedule** page lists everything upcoming and posted, across all videos and
platforms, with links.

### 6. If Gemini is out of quota: use another AI

In the editor, press **Use another AI**:

1. **Copy prompt:** copies exactly what Gemini would get, plus rules to reply with
   only JSON.
2. Paste it into ChatGPT, DeepSeek or any other AI, and copy its reply.
3. Paste the reply and press **Import clips**.

The import pulls the JSON out of chatty replies and code blocks, applies the same checks
as Gemini's answers, and replaces the AI clips you haven't edited.

---

## Features in detail

### Transcript sources

| Setting | Behaviour | Speed |
|---|---|---|
| **Auto** (default) | YouTube captions when available, otherwise Whisper | Seconds for most YouTube links |
| YouTube captions only | Never runs Whisper; without captions there's no transcript | Seconds |
| Whisper only | Always transcribes on your computer; the most accurate | Minutes (depends on model and hardware) |
| No transcript | Loudness and chat only, for gameplay without talking | Instant |

YouTube's auto-generated captions include the timing of every word, so word-by-word
captions stay in sync. Captions typed by the creator only have line timing, so word
timing is estimated. Uploaded files always use Whisper (or nothing).

### What Gemini reads

Only text, never the video itself. One request per video contains:

- the transcript in numbered lines with timestamps,
- the video title,
- your clip settings (number, length range, optional style),
- optional **loudness markers**: `(LOUD)`, `(VERY LOUD)`, and `(no speech · VERY LOUD)`
  lines for stretches without talking,
- optional **chat markers** for past live streams, e.g. `(CHAT x6.2: "no way", "w")`,
  meaning chat ran 6× faster than usual right after that line, with what viewers typed.

Gemini returns line ranges with a score from 0 to 100, which is its own judgment of hook
strength, standalone clarity and payoff. It also returns the title, hook title,
description and hashtags. The app then:
- treats the answer as untrusted and fixes line ranges,
- enforces your length range,
- cuts on word boundaries,
- drops overlapping clips and anything below your minimum score.

If the main model is overloaded, the app retries and then switches to the backup model.

### Captions and hook title

- **Captions:** word-by-word, with the spoken word highlighted. You set the font, size,
  colours, words on screen, height and uppercase.
- **Fonts:** Anton, Poppins ExtraBold and Bebas Neue are bundled. Bengali words switch
  automatically to the bundled Noto Sans Bengali, so they look the same on every
  computer.
- **Hook title:** a boxed banner for the first seconds. It's at the top for a single
  crop, and on the line between the two parts for streamer + content, so it doesn't
  cover the streamer's face.
- **Emoji** are left out of rendered videos because the renderer can't draw them.

---

## Settings reference

| Section | Setting | Default | Notes |
|---|---|---|---|
| Gemini | API key | none | Free at aistudio.google.com/apikey |
| | Model | `gemini-3.8-flash` | Change it if Google renames models |
| | Backup model | `gemini-3.5-flash-lite` | Used when the main model is overloaded |
| | Style of clips | none | e.g. "funny", "educational" |
| Clips | Shortest / longest clip | 20 s / 60 s | YouTube allows up to 3 minutes; Facebook Reels 3–90 s |
| | Clips per video | 10 | |
| | Minimum score | 0 | Hide Gemini's weaker suggestions |
| | Default hashtags | `#shorts` | Added to every clip |
| Captions | On, font, size, colours, words at once, height, uppercase | On, Anton, 110, white/yellow, 3, 30%, yes | Size is pixels on the 1080×1920 video |
| | Hook title: on, seconds, size, colours | On, 3 s, 80, black on white | |
| Publishing | Default publish time | 18:00 | In this computer's time zone |
| | Hours between Shorts | 24 | Spacing for Schedule all |
| | Category, Upload now visibility, made for kids | People & Blogs, public, no | |
| | Schedule all posts to | YouTube and Facebook | Only platforms that are connected |
| Transcription | Transcript source | Auto | See the table above |
| | Loudness hints / Live chat hints | On / On | |
| | Faster Whisper | On | About twice as fast, slightly less accurate |
| | Whisper model | small | tiny, base, small, medium, large-v3-turbo |
| | Run on | CPU | NVIDIA GPU (needs CUDA) or Apple GPU (experimental) |
| | Language | auto | e.g. `en`, `bn`, `hi` |
| Advanced | ffmpeg location | auto | Only if ffmpeg isn't found |

---

## Where things live

```
shorts-studio/
  start.bat / start.sh   start the app (first run sets everything up)
  app.py                 web server and API
  pipeline/              download, captions, transcription, chat, Gemini, render, YouTube, Facebook
  static/                the web pages (plain HTML/CSS/JS, no build step)
  fonts/                 caption fonts (SIL Open Font License)
  docs/                  setup guide and troubleshooting
  .venv/                 Python environment (created by the start script)
  data/                  everything you create (not in git)
    app.db               database: videos, clips, settings
    jobs/<id>/           one folder per video: source video, audio, transcript, chat summary, rendered clips
    models/              downloaded Whisper models
    youtube_client.json, youtube_token.json   YouTube connection (keep private)
    facebook.json        Facebook Page tokens (keep private)
```

Long videos take a lot of space: the source video plus a WAV copy of the audio (about
115 MB per hour). Delete a video from the Videos page to free its folder.

---

## Updating, moving and resetting

- **Update the app:** `git pull`, then start it as usual. If `requirements.txt`
  changed, the start script installs the new packages by itself.
- **Update the YouTube downloader** (when YouTube links stop working). With uv installed:
  `uv pip install --python .venv/bin/python -U "yt-dlp[default]"` (Windows:
  `--python .venv\Scripts\python.exe`). Without uv: `.venv/bin/python -m pip install -U "yt-dlp[default]"`
  (Windows: `.venv\Scripts\python.exe -m pip install -U "yt-dlp[default]"`).
- **Use another port:** `PORT=8080 ./start.sh` (Mac), or `set PORT=8080` then
  `start.bat` (Windows). If you connected YouTube with a *Web application* OAuth client,
  update its redirect address too (see Troubleshooting).
- **Keep data somewhere else:** set `SHORTS_DATA_DIR` to a folder before starting, e.g.
  `SHORTS_DATA_DIR=/Volumes/Big/shorts ./start.sh`.
- **Start fresh:** stop the app and delete the `data/` folder. This removes all videos,
  clips, settings and account connections.
- **Move to another computer:** copy the whole folder, excluding `.venv/` (it's rebuilt
  on first start). Copy `data/` too if you want your videos and settings.

---

## Privacy and limits

- **Gemini free tier:** Google may use what you send to improve its models. Only text is
  sent (transcript, title, markers), but avoid it for content you can't share.
- **YouTube:**
  - About 6 uploads a day on the default API quota.
  - Until Google audits your Cloud project, every API upload stays private, so scheduled
    Shorts won't go public.
  - While your Google app is in Testing mode, the sign-in expires after 7 days.
- **Facebook:** Reels must be 3–90 seconds, scheduled 10 minutes to 29 days ahead, and
  the API allows about 30 posts a day.
- **Local only:** the app listens on `127.0.0.1` and has no login. Don't expose the port
  to a network. `data/` holds your keys and tokens.

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) when something goes wrong.
