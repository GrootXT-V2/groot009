"""Context-aware speech transcription, without another SDK dependency."""
import json
import os
from pathlib import Path
import re
import urllib.request
import uuid


class UncertainTranscription(ValueError):
    """Speech was detected, but its full wording needs another recognition pass."""


def app_names():
    names = {"Claude"}
    for folder in (Path('/Applications'), Path.home() / 'Applications'):
        names.update(p.stem for p in folder.glob('*.app'))
    return sorted(names)[:80]


def correct_app_command(text):
    # Only a complete launch command, never dictation or a question about clouds.
    pattern = (r"^((?:(?:(?:hey|hay|hi|hy)\s+)?(?:fox|kurama)[, ]+)?"
               r"(?:please\s+)?(?:open|launch|start)\s*)(?:cloud|clawed|claud)"
               r"(\s+app)?(\s+(?:now|please))?([.!?]*)$")
    if not any((p / 'Claude.app').is_dir() for p in
               (Path('/Applications'), Path.home() / 'Applications')):
        return text
    return re.sub(pattern, lambda m: m[1].rstrip() + ' Claude' + (m[2] or '') +
                  (m[3] or '') + m[4], text.strip(), flags=re.I)


def transcribe_groq(audio):
    key = os.getenv('GROQ_API_KEY', '')
    if not key:
        raise RuntimeError('Groq speech recognition needs GROQ_API_KEY')
    boundary = 'groot-' + uuid.uuid4().hex
    fields = {
        'model': 'whisper-large-v3',
        'response_format': 'verbose_json', 'temperature': '0',
    }
    language = os.getenv('GROOT_STT_LANGUAGE', 'auto').strip().lower()
    if language and language != 'auto':
        fields['language'] = language
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode())
    parts.extend([audio.get_wav_data(convert_rate=16000, convert_width=2),
                  f'\r\n--{boundary}--\r\n'.encode()])
    request = urllib.request.Request(
        'https://api.groq.com/openai/v1/audio/transcriptions', data=b''.join(parts),
        headers={'Authorization': 'Bearer ' + key,
                 'User-Agent': 'Groot/1.0',
                 'Content-Type': 'multipart/form-data; boundary=' + boundary})
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
        segments = result.get('segments')
        if segments is not None:
            spoken = [s for s in segments if s.get('text', '').strip()]
            if not spoken or all(s.get('no_speech_prob', 1) >= 0.35 for s in spoken):
                return ''  # Keep silence/noise from waking the assistant.
            if any(s.get('no_speech_prob', 1) >= 0.35
                   or s.get('avg_logprob', -10) <= -0.7
                   or s.get('compression_ratio', 0) >= 2.4 for s in spoken):
                # Dropping just one segment can remove a negation, name, or
                # message body and turn the rest into a different command.
                raise UncertainTranscription('Retry the complete recording')
            return ' '.join(s['text'].strip() for s in spoken).strip()
        return result.get('text', '').strip()
