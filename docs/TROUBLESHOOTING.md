# Troubleshooting

Find your problem by area. Each entry gives what you see, why it happens, and the fix.
Messages in quotes are what the app shows.

- [Starting the app](#starting-the-app)
- [Setup checks and ffmpeg](#setup-checks-and-ffmpeg)
- [Downloading YouTube videos](#downloading-youtube-videos)
- [Transcription](#transcription)
- [Live chat](#live-chat)
- [Gemini](#gemini)
- [Using another AI (copy and paste)](#using-another-ai-copy-and-paste)
- [Editor](#editor)
- [Rendering and captions](#rendering-and-captions)
- [YouTube upload and scheduling](#youtube-upload-and-scheduling)
- [Facebook Reels](#facebook-reels)
- [Disk space and performance](#disk-space-and-performance)
- [Still stuck](#still-stuck)

---

## Starting the app

**Windows: double-clicking `start.bat` shows "Windows protected your PC".**
SmartScreen blocks scripts downloaded from the internet. Choose **More info → Run
anyway**, or right-click the file → Properties → tick **Unblock**.

**"Python 3.11 or 3.12 is needed".**
No suitable Python was found.
- Windows: `winget install Python.Python.3.12`, or install from python.org with **Add
  Python to PATH** ticked, then open a new terminal.
- Mac: `brew install python@3.12`, or install uv (`brew install uv`) and the script
  fetches Python itself.

**Windows: typing `python` opens the Microsoft Store.**
That's a Windows shortcut, not a real Python. Install Python as above. To stop the
redirect, go to Settings → Apps → Advanced app settings → **App execution aliases** and
turn off the two "python" entries.

**Mac: "permission denied: ./start.sh".**
The file lost its run permission, which can happen when it's copied from a zip. Run
`chmod +x start.sh` once.

**Windows: the window flashes and closes, or shows odd errors like `'echo.' is not recognized`.**
`start.bat` was saved with Mac/Linux line endings, which can happen if the folder came
through some zip tools or editors. Run it from a terminal (`start.bat`) to read the
error. Re-download the file, or re-save it with Windows (CRLF) line endings.

**Package installation fails on the first run.**
- **No internet or a proxy:** packages come from PyPI. Retry on a normal connection.
- **Very new Python (3.13+):** some packages may not have builds yet. Install 3.12 and
  delete the `.venv/` folder so it's recreated.
- After fixing, delete `.venv/` and start again for a clean install.

**"Address already in use", or the page shows a different app.**
Port 8000 is taken, often by a copy of this app that's already running. Close the other
window, or use another port: `PORT=8080 ./start.sh` (Mac), or `set PORT=8080` then
`start.bat` (Windows).

**The browser didn't open.**
Open **http://127.0.0.1:8000** yourself. Use `127.0.0.1`, not `localhost`, for YouTube
sign-in to work smoothly.

**The page is blank or doesn't react.**
Hard-refresh (Ctrl+Shift+R, or Cmd+Shift+R on Mac). After updating the app, the browser
may still have old scripts cached.

---

## Setup checks and ffmpeg

**"ffmpeg and ffprobe" is red.**
ffmpeg isn't installed or isn't on PATH.
- Windows: `winget install Gyan.FFmpeg`, then **close and reopen** the app's window (the
  PATH update only reaches new windows).
- Mac: `brew install ffmpeg-full`.
- Or set the folder that contains `ffmpeg` in **Settings → Advanced → ffmpeg location**.

**"ffmpeg can burn captions" warning.**
Your ffmpeg has no libass. That's typical of Homebrew's plain `ffmpeg` and some minimal
Linux builds. Install `ffmpeg-full` (Mac) or the gyan.dev full/essentials build
(Windows). Until then, turn off captions and hook titles in Settings to render without
them.

**I installed ffmpeg-full but the app still uses the old one.**
The app picks the first ffmpeg that can burn captions, checking Settings → Advanced, then
Homebrew's `ffmpeg-full`, then PATH. Restart the app after installing; it checks once at
startup and again whenever you save Settings.

---

## Downloading YouTube videos

**Downloads fail with errors about signatures, "n challenge", formats or JavaScript.**
yt-dlp needs a JavaScript runtime and an up-to-date version, because YouTube changes
often.
1. Make sure Deno or Node.js is installed (the setup check shows which one is found).
2. Update yt-dlp: with uv, `uv pip install --python .venv/bin/python -U "yt-dlp[default]"`
   (Windows: `--python .venv\Scripts\python.exe`). Without uv,
   `.venv/bin/python -m pip install -U "yt-dlp[default]"` (Windows:
   `.venv\Scripts\python.exe -m pip install -U "yt-dlp[default]"`).
3. Restart the app, and press **Retry** on the video.

**"Sign in to confirm you're not a bot", or HTTP 429 (Too Many Requests).**
YouTube is rate-limiting your connection. Wait a while, avoid many downloads in a row,
or try another network. Uploading the file yourself always works.

**"That link is a playlist".**
Paste a single video link. Links with `&list=...` usually still work; plain playlist
links don't.

**Private, age-restricted or members-only videos fail.**
The app downloads without your YouTube login, so download those another way and use
**Upload a file**.

**The download is slow or huge.**
Videos download at up to 1080p. A multi-hour stream can be several GB, so check your
free disk space.

---

## Transcription

**Transcribing takes forever.**
That's Whisper running on the CPU. Fixes, in order:
1. Settings → Transcript source → **Auto** (uses YouTube captions when available).
2. Keep **Faster Whisper** on.
3. Use a smaller model (`base` or `tiny`).
4. Run on **Apple GPU** (Mac) or **NVIDIA GPU** (Windows/Linux with CUDA). See
   [SETUP.md](SETUP.md#6-make-transcription-fast).

Changing these doesn't affect videos already transcribed; add the video again to redo
its transcript.

**"Transcribing with Whisper instead" note on a YouTube video.**
The video has no captions in the language you set (or none at all), so Auto fell back to
Whisper. That's expected.

**The first Whisper run "hangs" at 0%.**
It's downloading the model into `data/models/`: about 75 MB for `base`, 460 MB for
`small`, and 1.5 GB for `large-v3-turbo`. A warning about "unauthenticated requests to
the HF Hub" is harmless.

**NVIDIA GPU: errors mentioning CUDA, cuBLAS or cuDNN.**
The CUDA 12 runtime libraries (cuBLAS and cuDNN 9) aren't installed or aren't on PATH.
Install them, or set Settings → Run on → **CPU**.

**Apple GPU: errors or odd results.**
That backend is experimental. Switch back to **CPU**.

**The transcript is in the wrong language, or garbled.**
Set **Settings → Transcription → Language** (e.g. `bn`, `en`, `hi`) instead of
auto-detect, then add the video again.

**Word-by-word captions are slightly off.**
Captions typed by the creator only have line timing, so word timing is estimated.
Choose **Whisper only** for exact timing on that video.

**"No speech was found…".**
The video has no talking, or captions and Whisper were skipped. Turn on **Loudness hints**
(and **Live chat hints** for streams) so Gemini has something to read, then press **Run
AI again**.

---

## Live chat

**No "Live chat: N messages" label on a stream.**
- The video wasn't a live stream, or the streamer turned off chat replay. Nothing to do.
- **Live chat hints** was off when the video was added.
- YouTube didn't return it; the job's message says so. Add the video again later.

**"Reading the live chat replay…" takes minutes.**
Chat downloads in pages: roughly 3 minutes for a 12-hour stream. It only happens once
per video.

**Gemini picks moments where the streamer just asked chat to type.**
Gemini is told to ignore those, but it can still be fooled by them. Delete those clips,
or raise **Minimum score**.

---

## Gemini

**"No Gemini API key."**
Add one in Settings (free at aistudio.google.com/apikey).

**"Gemini rejected the API key."**
The key is wrong, deleted, or restricted. Create a new key and paste it again (the field
shows only the last 4 characters of the saved key).

**"Gemini rate limit reached (free tier)…".**
Too many requests in a short time, or the daily free quota is used up. Wait a minute
(or until tomorrow for the daily limit), then press **Run AI again**. Or use **Use another
AI**.

**"Gemini is overloaded right now (Google's side)…".**
Google returned "high demand" (503) for both the main and the backup model. It's usually
temporary; try again in a few minutes, or use another AI.

**"Gemini model '…' was not found."**
Google renamed or retired the model. Put a current name from
[Google's model list](https://ai.google.dev/gemini-api/docs/models) into Settings → Model
(and Backup model).

**"Gemini took more than 2 minutes to answer."**
Very long prompts (multi-hour streams with lots of speech) or a slow moment at Google.
Press Run AI again.

**"Gemini found no clips that fit your length settings."**
The suggestions were outside your shortest/longest clip range, or overlapped. Widen the
range in Settings and Run AI again.

**Titles and hook titles come out in English for a non-English video.**
Gemini follows the transcript language, but the video title can pull it towards
English. Edit them in the editor. A setting for the title language is planned.

**"Run AI again" removed my clips.**
It replaces only AI clips you never edited. Clips you created, or AI clips you changed in
any way, are kept.

---

## Using another AI (copy and paste)

**"Copy the prompt first, then paste the AI's reply."**
Line numbers in the reply refer to the prompt you copied, so the app needs that copy.
Press **Copy prompt** in the same panel first.

**"Couldn't find a JSON list in that reply."**
The AI answered with only text. Ask it: "Reply with only the JSON array, no other
text", and paste again.

**"None of the clips in that reply could be read (…)".**
The items are missing required fields (`start_line`, `end_line`, `score`, `title`). Paste
the prompt again in a new chat; the format rules are at the end of the prompt.

**"…none of its clips fit your length settings…".**
The AI ignored the length range. Ask it to follow the seconds limits, or widen the range
and copy the prompt again.

**The AI's reply stops halfway, or it says the text is too long.**
Prompts for long videos can exceed free chat limits (the panel warns above 40,000
characters). Use a tool with a larger limit.

**The Copy button doesn't copy.**
Some browsers block clipboard access. The text is selected anyway, so press Ctrl+C
(Cmd+C on Mac).

---

## Editor

**"Your browser can't play this video's format."**
The source is HEVC or another codec your browser can't play, which is common with iPhone
footage. Convert it to H.264 MP4 first (e.g. in HandBrake), or use Chrome or Edge. The
home page warns about this when the video is added.

**Seeking jumps back to the start, or the waveform is missing.**
Hard-refresh the page. If it keeps happening, the video file may be damaged; delete the
video and add it again.

**I can't drag to create a clip.**
Drag on the waveform, not on an existing clip. When zoomed out on a long video a small
drag may be ignored; zoom in, or use **+ Clip at playhead**.

**"A clip must be at least half a second long" / "The clip ends after the video does."**
Adjust the start and end times.

**The crop box or layout boxes are missing.**
The single crop box shows only when a clip is selected. Streamer + content boxes show for
the whole video. Wait for the video to load, then select a clip.

**"This clip is rendering or uploading. Wait for it to finish."**
Clips and videos can't be deleted while they're rendering or posting.

---

## Rendering and captions

**"This ffmpeg can't draw captions or hook titles…".**
See [Setup checks and ffmpeg](#setup-checks-and-ffmpeg), or turn off captions and hook
titles to render without them.

**"This ffmpeg has no H.264 encoder (libx264)."**
Install a full ffmpeg build (gyan.dev full/essentials on Windows, `ffmpeg-full` on Mac).

**"ffmpeg failed: …".**
The text after it is ffmpeg's own error. Common causes: the disk is full, the source video
was deleted or moved, or the clip starts after the video ends.

**Captions show boxes or missing letters.**
The caption font has no letters for that script. Bengali switches to the bundled Noto Sans
Bengali automatically. For other scripts (Hindi, Arabic and so on) the renderer borrows a
font from your computer, which may not exist on every machine. Choose a different font in
Settings, or add a suitable `.ttf` to `fonts/`.

**Emoji are missing from captions or the hook title.**
The renderer can't draw colour emoji, so they're removed on purpose.

**The hook banner covers something important.**
For a single crop it sits near the top; for Streamer + content it's on the line between
the parts. Shorten the text, lower **Hook title → Text size** or **Show for**, or clear the
hook for that clip.

**The render looks stretched or cropped wrongly.**
Check the layout boxes: they keep the right shape automatically, so stretching usually
means a very small box scaled up (blurry rather than stretched). Make the box bigger.
Portrait phone videos are handled using their rotation flag.

**"Edited since render" won't go away.**
Any change to the clip's time, crop, hook title, layout or caption settings makes the
render out of date. Press **Render again**. Posting re-renders by itself.

---

## YouTube upload and scheduling

**Google sign-in says "Access blocked: … has not completed the Google verification process" / error 403 access_denied.**
Your Google account isn't a test user. Add it in Google Auth Platform → **Audience → Test
users**, then press Connect YouTube again.

**"Error 400: redirect_uri_mismatch".**
You created a **Web application** OAuth client instead of a **Desktop app**. Either make a
Desktop app client and upload its JSON, or add exactly
`http://127.0.0.1:8000/auth/youtube/callback` to the web client's authorised redirect
URIs (use your port if it isn't 8000).

**"This sign-in link expired. Press Connect YouTube again."**
The app restarted between opening Google's page and coming back. Press Connect again.

**"Google didn't return a long-lived login…".**
Google skipped the refresh token because you approved this app before. Remove its
access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions),
then connect again.

**"The YouTube login has expired. Reconnect in Settings."**
In Testing mode Google ends logins after 7 days. Reconnect, and press **Publish app** in
Google Auth Platform → Audience to stop it happening (see
[SETUP.md](SETUP.md#45-two-google-rules-youll-want-to-deal-with)).

**"This Google account has no YouTube channel yet."**
Create a channel on youtube.com with that account, or connect the account that owns the
channel.

**Uploaded videos stay private, and scheduled ones never go public.**
Google locks uploads from unaudited API projects to private. Apply with the
[YouTube API audit form](https://support.google.com/youtube/contact/yt_api_form). Until
then, publish by hand in YouTube Studio, or Download and upload yourself.

**"YouTube's daily API quota is used up…".**
About 6 uploads a day on the default quota. It resets at midnight Pacific time. Spread
uploads out, or request more quota in Google Cloud.

**"Pick a publish time at least 10 minutes from now." / "The scheduled time has already passed…".**
YouTube needs a future time. If a queued upload waited too long (for example, the app
was closed), pick a new time and schedule again.

**I changed a clip after uploading, but YouTube still shows the old one.**
Edits in the app don't update YouTube. Change it in YouTube Studio, or delete it there
and upload again.

**Does my computer need to be on at the scheduled time?**
No. The video is uploaded right away and YouTube publishes it at that time. The
computer only needs to be on while uploading.

---

## Facebook Reels

**"No Pages found that you can post to…".**
When generating the token in Graph API Explorer you didn't select the Page, or didn't
grant the permissions. Generate a new token with `pages_show_list`,
`pages_read_engagement` and `pages_manage_posts`, and pick the Page when asked.

**"The Facebook login has expired or was revoked…".**
The token was revoked, for example after a password change or removing the app's access.
Generate a new token and press Connect again.

**"Facebook refused: the app is missing a permission…".**
Reconnect with all three permissions. Your Facebook account must also be allowed to create
content on the Page.

**"Facebook Reels must be 3–90 seconds…".**
Trim the clip, or post it to YouTube only. **Schedule all** skips longer clips for
Facebook and says so.

**"Facebook needs the publish time to be at least 10 minutes from now." / "…up to 29 days ahead."**
Pick a time in that window.

**"Facebook's posting limit was reached…".**
About 30 Reels a day through the API. Try again later.

**Reels post fine, but other people can't see them.**
Switch the Meta app from **Development** to **Live** mode in its dashboard (it may ask for
a privacy policy URL).

---

## Disk space and performance

**The `data/` folder is huge.**
Each video keeps its source file, a WAV copy of the audio (about 115 MB per hour) and its
rendered clips. Delete videos you're done with from the Videos page. Chat replays are
saved as a small summary, and the raw download is deleted.

**Everything is slow while a long video transcribes.**
Whisper uses the CPU heavily. Rendering and uploading run in a separate background lane,
so they don't wait for transcription, but they share the same CPU.

**I closed the app in the middle of a job.**
Start it again: unfinished downloads, transcriptions, renders and uploads resume
automatically. Uploads start over from the beginning.

---

## Still stuck

1. Run the app from a terminal (`./start.sh` or `start.bat`) and read the messages; errors
   from the background worker print there.
2. Press **Retry** on failed videos after fixing the cause.
3. To rule out a broken setup, delete `.venv/` and start again (it's recreated, and your
   data stays). As a last resort, stop the app and move `data/` aside to start fresh.
