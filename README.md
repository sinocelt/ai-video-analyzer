# AI Video Analyzer (Self-Hosted, Near-Zero Cost)

One-page Streamlit app that turns a video into:

- 3 SEO-optimized titles
- an engaging description
- 5-10 relevant hashtags
- a thumbnail image prompt

Pipeline:

1. Upload a video file or paste a video URL.
2. Extract audio with `ffmpeg`.
3. Transcribe locally with OpenAI Whisper.
4. Generate marketing assets with Gemini API or Groq API.
5. Save outputs locally in `data/results`.

## Why this stack

- Whisper runs locally, so transcription has no per-call API fee.
- Gemini/Groq free tiers can keep generation cost at zero for low-volume personal use.
- Streamlit gives a simple one-page web app with fast iteration.

## Requirements

- Python 3.10+ (3.11 recommended)
- `ffmpeg` installed on your machine
- At least one API key:
  - Gemini API key from Google AI Studio, or
  - Groq API key from Groq Console

## Setup

1. Install `ffmpeg`:

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y ffmpeg

# macOS (Homebrew)
brew install ffmpeg
```

2. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install Python dependencies:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

4. Configure environment variables:

```bash
cp .env.example .env
```

Then set keys in `.env`:

- `LLM_PROVIDER=auto` (recommended)
- `GEMINI_API_KEY=...`
- `GROQ_API_KEY=...`

`auto` mode can use Gemini first and automatically fall back to Groq.

## Run

```bash
streamlit run app.py
```

Open the URL shown in the terminal (usually `http://localhost:8501`).

## Deploy to a Domain (VPS + Nginx)

Use the full deployment guide:

- [DEPLOY_VPS_NGINX.md](DEPLOY_VPS_NGINX.md)

Included templates:

- `deploy/systemd/ai-video-analyzer.service`
- `deploy/nginx/ai-video-analyzer.conf`

## How to use

1. Choose LLM provider mode in the sidebar:
   - `Auto (Gemini -> Groq fallback)` (recommended)
   - `Gemini only`
   - `Groq only`
2. Add API keys in sidebar (or keep them in `.env`).
3. Choose a Whisper model (`base` is a good CPU default).
4. Select input type:
   - upload a file, or
   - paste a URL.
5. Click **Analyze Video**.
6. Review outputs and use **Regenerate Assets** for alternatives.
7. Download JSON or Markdown from the output section.

## Output storage

- JSON runs are saved to `data/results/analysis-*.json`.
- Temporary job files are stored in `data/jobs/`.

## Notes and tradeoffs

- This design is "near-zero cost", not guaranteed forever:
  Gemini/Groq free-tier quotas and policies can change.
- URL processing uses `yt-dlp`; only process content you have rights to use.
- Large videos can be slow on CPU. Use smaller Whisper models for speed.
- In `auto` mode, temporary Gemini 503 issues can fail over to Groq automatically.
