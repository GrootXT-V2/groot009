"""Context-aware speech transcription, without another SDK dependency."""
import json
import os
from pathlib import Path
import re
import urllib.request
import uuid


def app_names():
    names = {"Claude", "Kurama", "Hey Fox"}
    for folder in (Path('/Applications'), Path.home() / 'Applications'):
        names.update(p.stem for p in folder.glob('*.app'))
    return sorted(names)[:80]


def correct_app_command(text):
    # Only a complete launch command, never dictation or a question about clouds.
    pattern = (r"^((?:(?:hey|hay|hi|hy)\s+(?:fox|kurama)[, ]+)?"
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
        'model': 'whisper-large-v3-turbo', 'language': 'en',
        'response_format': 'json', 'temperature': '0',
        'prompt': 'Desktop assistant vocabulary: ' + ', '.join(app_names()),
    }
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
        return json.load(response)['text'].strip()
