# ElevenLabs TTS Streamlit App

A simple Streamlit app that uses the ElevenLabs Text-to-Speech API to generate speech from text with options to preview, regenerate, reject, and save audio.

## Features
- Enter text and generate speech with ElevenLabs voices/models
- Preview audio in the browser
- Regenerate with same params
- Reject (clear) the current audio
- Save MP3 to an `outputs/` folder and download as a file

## Setup
1. Ensure Python 3.9+
2. Install dependencies:
   - `streamlit`
   - `elevenlabs`
3. Provide your ElevenLabs API key in one of the following ways:
   - Environment variable `ELEVENLABS_API_KEY`
   - Streamlit secrets: add to `.streamlit/secrets.toml` as `elevenlabs_api_key = "YOUR_KEY"`

Example secrets file:

```toml
# .streamlit/secrets.toml
elevenlabs_api_key = "YOUR_API_KEY"
```

## Run
Start the app and open the provided local URL in your browser:

```bash
streamlit run app.py
```

On first run, choose a model and voice in the sidebar. If your voices fail to load automatically, paste a Voice ID manually.

Saved files will be written to `outputs/`.
