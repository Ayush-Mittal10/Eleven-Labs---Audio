import os
import io
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

import streamlit as st


# ---------------
# Helper functions
# ---------------
def safe_filename(s: str, *, max_len: int = 80, ext: Optional[str] = None) -> str:
	"""Return a Windows-safe file name.
	- Replaces invalid chars <>:"/\|?* with underscores
	- Collapses whitespace to underscores
	- Trims trailing dots/spaces/underscores
	- Avoids reserved names like CON, PRN, AUX, NUL, COM1-9, LPT1-9
	- Truncates to max_len (before extension)
	- If ext is provided, appends it (e.g., 'mp3')
	"""
	import re

	s = (s or "").strip()
	if not s:
		s = "tts"

	# Replace invalid characters
	s = re.sub(r'[<>:\"/\\|?*]+', "_", s)
	# Replace whitespace with underscores
	s = re.sub(r"\s+", "_", s)
	# Trim undesired trailing/leading chars
	s = s.strip(" ._") or "tts"

	# Avoid reserved device names
	reserved = {
		"CON", "PRN", "AUX", "NUL",
		"COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
		"LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
	}
	if s.upper() in reserved:
		s = f"_{s}"

	# Truncate
	if max_len and len(s) > max_len:
		s = s[:max_len].rstrip(" ._") or "tts"

	if ext:
		ext = ext.lstrip('.')
		return f"{s}.{ext}"
	return s
@st.cache_resource(show_spinner=False)
def get_elevenlabs_client(api_key: Optional[str]):
	if not api_key:
		return None
	try:
		# Lazy import so app loads without the package for users reading the UI
		from elevenlabs import ElevenLabs  # type: ignore

		return ElevenLabs(api_key=api_key)
	except Exception as e:  # pragma: no cover
		st.error(f"Failed to initialize ElevenLabs client: {e}")
		return None


def list_voices(client) -> List[Dict[str, Any]]:
	try:
		# SDK returns a response object with .voices list (each has .name and .voice_id)
		res = client.voices.get_all()
		# Normalize to list of dicts to avoid SDK types in session_state
		voices = []
		for v in getattr(res, "voices", []) or []:
			voices.append({
				"name": getattr(v, "name", "Unnamed"),
				"voice_id": getattr(v, "voice_id", None),
				"labels": getattr(v, "labels", None),
			})
		return voices
	except Exception as e:
		st.warning(f"Could not fetch voice list: {e}")
		return []


def synthesize(
	client,
	text: str,
	voice_id: str,
	model_id: str = "eleven_multilingual_v2",
	output_format: str = "mp3_44100_128",
	voice_settings: Optional[Dict[str, Any]] = None,
	pronunciation_locators: Optional[List[Dict[str, Optional[str]]]] = None,
) -> Optional[bytes]:
	if not client:
		st.error("No ElevenLabs client available. Provide an API key.")
		return None
	if not text.strip():
		st.warning("Enter some text to synthesize.")
		return None
	try:
		# Build VoiceSettings if provided
		vs_obj = None
		if voice_settings:
			try:
				from elevenlabs.types.voice_settings import VoiceSettings  # type: ignore
				vs_obj = VoiceSettings(**voice_settings)
			except Exception as ie:
				st.warning(f"Ignoring invalid voice settings: {ie}")
				vs_obj = None

		# Coerce pronunciation locators into SDK objects if provided
		locators_obj = None
		if pronunciation_locators:
			try:
				from elevenlabs.types import PronunciationDictionaryVersionLocator as Locator  # type: ignore
				locators_obj = []
				for loc in pronunciation_locators:
					if isinstance(loc, dict):
						locators_obj.append(Locator(**loc))
					else:
						locators_obj.append(loc)
			except Exception:
				locators_obj = pronunciation_locators

		# The SDK yields audio chunks; collect into bytes for Streamlit
		audio_stream = client.text_to_speech.convert(
			voice_id=voice_id,
			model_id=model_id,
			text=text,
			output_format=output_format,
			voice_settings=vs_obj,
			pronunciation_dictionary_locators=locators_obj,
		)

		buf = io.BytesIO()
		for chunk in audio_stream:
			if isinstance(chunk, (bytes, bytearray)):
				buf.write(chunk)
		return buf.getvalue()
	except Exception as e:
		st.error(f"TTS generation failed: {e}")
		return None


def ensure_outputs_dir() -> str:
	base = os.path.join(os.getcwd(), "outputs")
	os.makedirs(base, exist_ok=True)
	return base


def save_audio_to_disk(audio_bytes: bytes, suggested_name: str) -> str:
	outputs = ensure_outputs_dir()
	timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
	base = safe_filename(suggested_name, ext=None)
	filename = f"{base}-{timestamp}.mp3"
	path = os.path.join(outputs, filename)
	with open(path, "wb") as f:
		f.write(audio_bytes)
	return path


# ---------------
# Streamlit UI
# ---------------
st.set_page_config(page_title="TTS with ElevenLabs", page_icon="🔊", layout="centered")
st.title("Text-to-Speech Generator 🔊")

# Ensure session state is available before sidebar logic uses it
ss = st.session_state
ss.setdefault("last_audio", None)
ss.setdefault("last_text", "")
ss.setdefault("last_params", {})
ss.setdefault("history", [])

# Sidebar for configuration
with st.sidebar:
	st.header("Configuration")
	# API key from env first, then secrets if available
	default_key = os.getenv("ELEVENLABS_API_KEY", "")
	try:
		# Accessing st.secrets may raise if no secrets file exists
		secret_key = st.secrets["elevenlabs_api_key"]
		if secret_key:
			default_key = secret_key
	except Exception:
		pass
	api_key = st.text_input("ElevenLabs API Key", value=default_key, type="password", help="Stored only for this session. You can also set ELEVENLABS_API_KEY env var or add st.secrets['elevenlabs_api_key'].")

	model = st.selectbox(
		"Model",
		options=[
			"eleven_multilingual_v2",
			"eleven_flash_v2",
		],
		index=0,
		help="Recommended: multilingual_v2 for quality, flash_v2 for speed.",
	)

	client = get_elevenlabs_client(api_key)
	voices = list_voices(client) if client else []

	voice_names = [f"{v['name']} ({v['voice_id'][:8]}…)" if v.get("voice_id") else v["name"] for v in voices]
	if voices:
		selected_idx = st.selectbox("Voice", options=list(range(len(voices))), format_func=lambda i: voice_names[i])
		voice_id = voices[selected_idx]["voice_id"]
	else:
		st.info("Enter a Voice ID (couldn't load your voices).")
		voice_id = st.text_input("Voice ID", value="", placeholder="e.g., 21m00Tcm4TlvDq8ikWAM")

	with st.expander("Voice settings", expanded=False):
		use_defaults = st.checkbox("Use ElevenLabs defaults", value=True, help="When enabled, server defaults are used for voice behavior.")
		if not use_defaults:
			speed = st.slider("Speed", min_value=0.5, max_value=2.0, value=1.0, step=0.05, help="Playback speed multiplier (1.0 is normal).")
			stability = st.slider("Stability", min_value=0.0, max_value=1.0, value=0.5, step=0.01, help="Lower = more expressive; higher = more consistent.")
			similarity_boost = st.slider("Similarity boost", min_value=0.0, max_value=1.0, value=0.75, step=0.01, help="Higher keeps voice closer to the original.")
			style = st.slider("Style exaggeration", min_value=0.0, max_value=1.0, value=0.0, step=0.01, help="Amount of stylistic emphasis.")
			use_speaker_boost = st.checkbox("Speaker boost", value=True, help="Enhance presence and clarity.")
			current_voice_settings = {
				"speed": float(speed),
				"stability": float(stability),
				"similarity_boost": float(similarity_boost),
				"style": float(style),
				"use_speaker_boost": bool(use_speaker_boost),
			}
		else:
			current_voice_settings = None

	# Optional pronunciation dictionary
	with st.expander("Pronunciation dictionary (.pls)", expanded=False):
		include_pls = st.checkbox("Include dictionary from file", value=False, help="Use a PLS file to tweak pronunciations.")
		pls_default_path = os.path.join(os.getcwd(), "dictionary.pls")
		pls_path = st.text_input("PLS file path", value=pls_default_path)
		dict_name = st.text_input("Dictionary name", value="CustomPronunciations")

		# Prepare locator lazily when generating
		pronunciation_locators = None
		if include_pls:
			if not os.path.exists(pls_path):
				st.warning(f"PLS file not found at: {pls_path}")
			elif not client:
				st.info("Provide API key to upload/use a pronunciation dictionary.")
			else:
				ss.setdefault("_pls_cache", {})
				# Cache by path+name+mtime to avoid duplicate uploads in a session
				try:
					mtime = os.path.getmtime(pls_path)
				except Exception:
					mtime = 0
				cache_key = f"{pls_path}::{dict_name}::{mtime}"
				cache_hit = ss["_pls_cache"].get(cache_key)
				if cache_hit:
					pronunciation_locators = cache_hit
				else:
					try:
						from elevenlabs.types import PronunciationDictionaryVersionLocator  # type: ignore
						with open(pls_path, "rb") as f:
							file_bytes = f.read()
						# Upload as a new versioned dictionary (session scoped)
						resp = client.pronunciation_dictionary.add_from_file(name=dict_name, file=file_bytes)
						locator = PronunciationDictionaryVersionLocator(
							pronunciation_dictionary_id=resp.id,
							version_id=getattr(resp, "version_id", None),
						)
						pronunciation_locators = [locator]
						ss["_pls_cache"][cache_key] = pronunciation_locators
						st.caption(f"Using dictionary '{dict_name}' (id={resp.id}) for this session.")
					except Exception as e:
						st.warning(f"Could not use PLS dictionary: {e}")
						pronunciation_locators = None


# Main input
text = st.text_area(
	"Enter text to synthesize:",
	value=ss.get("last_text", ""),
	height=180,
	placeholder="Type or paste the text you want to convert to speech…",
)

col_gen, col_clear = st.columns([1, 1])
with col_gen:
	generate = st.button("Generate Audio", type="primary")
with col_clear:
	clear_text = st.button("Clear Text")

if clear_text:
	text = ""
	ss["last_text"] = ""


# Generate logic
if generate:
	if not api_key:
		st.error("Please provide your ElevenLabs API key in the sidebar.")
	elif not voice_id:
		st.error("Please select or enter a Voice ID.")
	else:
		with st.spinner("Generating audio…"):
			audio_bytes = synthesize(
				client,
				text,
				voice_id=voice_id,
				model_id=model,
				voice_settings=current_voice_settings,
				pronunciation_locators=pronunciation_locators,
			)
		if audio_bytes:
			ss["last_audio"] = audio_bytes
			ss["last_text"] = text
			ss["last_params"] = {
				"voice_id": voice_id,
				"model": model,
				"voice_settings": current_voice_settings,
				# Store a serializable form for regeneration (id/version_id dicts)
				"pronunciation_locators": [
					{"pronunciation_dictionary_id": getattr(l, "pronunciation_dictionary_id", None), "version_id": getattr(l, "version_id", None)}
					for l in (pronunciation_locators or [])
				] if pronunciation_locators else None,
			}


# Render audio player and actions
if ss.get("last_audio"):
	st.subheader("Preview")
	st.audio(ss["last_audio"], format="audio/mp3")

	col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
	with col1:
		if st.button("Regenerate"):
			with st.spinner("Regenerating…"):
				params = ss.get("last_params", {})
				audio_bytes = synthesize(
					client,
					ss.get("last_text", ""),
					voice_id=params.get("voice_id", ""),
					model_id=params.get("model", model),
					voice_settings=params.get("voice_settings"),
					pronunciation_locators=params.get("pronunciation_locators"),
				)
			if audio_bytes:
				ss["last_audio"] = audio_bytes
	with col2:
		if st.button("Reject"):
			ss["last_audio"] = None
			st.info("Audio discarded.")
			# Force a small rerun to clear the player
			time.sleep(0.1)
			st.rerun()
	with col3:
		# Save to disk
		if st.button("Save to disk"):
			try:
				suggested_base = (ss.get("last_text", "")[:24] or "tts")
				path = save_audio_to_disk(ss["last_audio"], suggested_base)
				ss["history"].append({
					"name": os.path.basename(path),
					"path": path,
					"bytes_len": len(ss["last_audio"]),
					"when": datetime.now().isoformat(timespec="seconds"),
				})
				st.success(f"Saved: {path}")
			except Exception as e:
				st.error(f"Save failed: {e}")
	with col4:
		# Client-side download
		suggested_name = safe_filename((ss.get("last_text", "")[:24] or "tts"), ext="mp3")
		st.download_button(
			label="Download MP3",
			data=ss["last_audio"],
			file_name=suggested_name,
			mime="audio/mpeg",
		)


# Saved history
if ss.get("history"):
	st.divider()
	st.subheader("Saved Clips")
	for item in reversed(ss["history"][-10:]):
		st.write(f"• {item['when']} — {item['name']} ({item['bytes_len']} bytes)")


st.caption(
	"Tip: Set ELEVENLABS_API_KEY as an environment variable or add it to st.secrets for convenience."
)

