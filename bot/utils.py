import os
import tempfile
from contextlib import contextmanager
import subprocess
import shutil

@contextmanager
def temp_audio_file(audio_data):
    """Контекстный менеджер для временных аудиофайлов"""
    temp_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        temp_file.write(audio_data)
        temp_file.close()
        yield temp_file.name
    finally:
        if temp_file and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

def split_long_message(text, max_length=4000):
    """Разбивает длинное сообщение на части"""
    if len(text) <= max_length:
        return [text]
    
    parts = []
    while len(text) > max_length:
        # Ищем последний перенос строки или точку перед лимитом
        split_pos = text.rfind('\n', 0, max_length)
        if split_pos == -1:
            split_pos = text.rfind('. ', 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        
        parts.append(text[:split_pos + 1])
        text = text[split_pos + 1:]
    
    if text:
        parts.append(text)
    
    return parts

def format_voice_info(voice, speed):
    """Форматирует информацию о настройках голоса"""
    from config import Config
    voice_name = Config.VOICES.get(voice, voice)
    speed_name = next((name for id, (name, _) in Config.SPEEDS.items() 
                      if abs(Config.SPEEDS[id][1] - speed) < 0.1), f"{speed}x")
    
    return f"Голос: {voice_name}\nСкорость: {speed_name}"


def convert_mp3_to_ogg_opus(mp3_path):
    """Пытается конвертировать MP3 в OGG/OPUS с помощью ffmpeg.

    Возвращает путь к ogg-файлу или None, если конвертация невозможна.
    """
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return None

    out_fd, out_path = tempfile.mkstemp(suffix='.ogg')
    os.close(out_fd)

    cmd = [ffmpeg, '-y', '-i', mp3_path, '-c:a', 'libopus', '-b:a', '64k', out_path]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if proc.returncode == 0 and os.path.exists(out_path):
            return out_path
        else:
            try:
                os.unlink(out_path)
            except Exception:
                pass
            return None
    except Exception:
        try:
            os.unlink(out_path)
        except Exception:
            pass
        return None