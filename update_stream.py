#!/usr/bin/env python3

import json
import re
import subprocess
import sys
import requests
import random
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

CONFIG_FILE = "config.json"
COOKIE_FILE = "cookies.txt"

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)


def load_config() -> Dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    if "channels" not in config or not isinstance(config["channels"], list):
        raise ValueError("config.json içinde 'channels' listesi bulunamadı.")

    if not config["channels"]:
        raise ValueError("config.json içinde kanal listesi boş.")

    config.setdefault("quality", "best[height<=1080][fps<=50]/best")
    config.setdefault("output_folder", "playlist")
    config.setdefault("output_playlist", "playlist.m3u8")
    config.setdefault("resolution", "1280x720")
    config.setdefault("bandwidth", "1280000")
    
    return config


def safe_filename(name: str) -> str:
    """Kanal adından güvenli dosya adı oluşturur"""
    replacements = {
        "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
        "Ç": "C", "Ğ": "G", "İ": "I", "Ö": "O", "Ş": "S", "Ü": "U",
        " ": "_", "-": "_"
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    
    # Sadece alfanumeric ve underscore kalacak
    name = re.sub(r'[^a-zA-Z0-9_]', '', name)
    return f"{name}.m3u8"


def is_token_channel(url: str) -> bool:
    return url == "token_kanal"


def is_atv_avrupa_name(name: str) -> bool:
    lower = name.lower()
    return "atv" in lower and "avrupa" in lower


def is_eurostar_name(name: str) -> bool:
    lower = name.lower()
    return "euro star" in lower or "eurostar" in lower or "star avrupa" in lower


def is_show_turk_name(name: str) -> bool:
    lower = name.lower()
    return "show" in lower and ("türk" in lower or "turk" in lower)


def load_netscape_cookies(cookie_file: str = COOKIE_FILE) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    path = Path(cookie_file)

    if not path.exists():
        return cookies

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    name = parts[5].strip()
                    value = parts[6].strip()
                    if name:
                        cookies[name] = value
    except Exception as e:
        print(f"   ⚠️ Cookie okuma hatası: {e}")

    return cookies


def get_atv_avrupa_stream() -> Optional[str]:
    headers = {
        "X-isApp": "1",
        "X-Rand": str(int(time.time() * 1000)),
        "Origin": "https://www.atvavrupa.tv",
        "Referer": "https://www.atvavrupa.tv/",
        "User-Agent": CHROME_UA,
    }

    stream_url = "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa_576p.m3u8"
    encoded = urllib.parse.quote(stream_url)
    token_url = f"https://securevideotoken.tmgrup.com.tr/webtv/secure?{random.randint(1, 1000000)}&url={encoded}&url2={encoded}"

    cookies = load_netscape_cookies()

    try:
        response = requests.get(token_url, headers=headers, cookies=cookies if cookies else None, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get("Success") and data.get("Url"):
            print("   ✅ ATV Avrupa stream alındı")
            return data.get("Url")
        return None
    except Exception as e:
        print(f"   ❌ ATV Avrupa hatası: {e}")
        return None


def get_eurostar_stream() -> Optional[str]:
    page_url = "https://www.eurostartv.com.tr/canli-izle"
    headers = {"User-Agent": CHROME_UA}

    try:
        response = requests.get(page_url, headers=headers, timeout=15)
        html = response.text

        pattern = r"var liveUrl = 'https://dygvideo\.dygdigital\.com/live/hls/staravrupa\?token=([a-f0-9]+)';"
        match = re.search(pattern, html)

        if not match:
            return None

        token = match.group(1)
        token_url = f"https://dygvideo.dygdigital.com/live/hls/staravrupa?token={token}"

        response2 = requests.get(token_url, headers=headers, allow_redirects=False, timeout=10)

        if response2.status_code == 302:
            master_url = response2.headers.get("Location")
            if master_url:
                match = re.match(r"(.*/)live\.m3u8\?(.*)", master_url)
                if match:
                    stream_url = f"{match.group(1)}live_1080p3000000kbps/index.m3u8?{match.group(2)}"
                    print("   ✅ EuroStar stream alındı")
                    return stream_url
                return master_url
        return None
    except Exception as e:
        print(f"   ❌ EuroStar hatası: {e}")
        return None


def get_show_turk_stream() -> Optional[str]:
    url = "https://www.showturk.com.tr/canli-yayin"
    pattern = r"playlist\.m3u8\?e=(\d+)&st=([^\"\s&]+)"

    try:
        response = requests.get(url, headers={"User-Agent": CHROME_UA}, timeout=10)
        html = response.text
        match = re.search(pattern, html)

        if match:
            e, st = match.groups()
            stream_url = f"https://ciner-live.ercdn.net/showturk/playlist.m3u8?e={e}&st={st}&tv=1"
            print("   ✅ Show Türk stream alındı")
            return stream_url
        return None
    except Exception as e:
        print(f"   ❌ Show Türk hatası: {e}")
        return None


def get_youtube_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    cmd = [
        "yt-dlp",
        "-g",
        "--cookies", COOKIE_FILE,
        "--js-runtimes", "deno",
        "-f", quality,
        youtube_url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        
        for line in lines:
            if "manifest" in line or ".m3u8" in line:
                return line
        return lines[0] if lines else None
    except Exception as e:
        print(f"   ❌ YouTube hatası: {e}")
        return None


def get_stream_url(channel: Dict, quality: str) -> Optional[str]:
    channel_name = channel.get("name", "")
    channel_url = channel.get("url", "")

    if is_token_channel(channel_url):
        if is_atv_avrupa_name(channel_name):
            return get_atv_avrupa_stream()
        elif is_eurostar_name(channel_name):
            return get_eurostar_stream()
        elif is_show_turk_name(channel_name):
            return get_show_turk_stream()
        return None
    
    elif ".m3u8" in channel_url.lower():
        return channel_url
    
    elif "youtube.com" in channel_url or "youtu.be" in channel_url:
        return get_youtube_stream_url(channel_url, quality)
    
    return None


def create_channel_m3u8(stream_url: str, resolution: str, bandwidth: str, output_path: Path) -> bool:
    """Her kanal için ayrı M3U8 dosyası oluşturur"""
    try:
        content = f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={resolution}
{stream_url}
"""
        output_path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        print(f"   ❌ Dosya yazma hatası: {e}")
        return False


def main() -> int:
    print("=" * 60)
    print("🎬 TV Kanalları - Ayrı M3U8 Dosyaları Oluşturucu")
    print("=" * 60)
    print(f"🕐 Başlangıç: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        config = load_config()
    except Exception as e:
        print(f"❌ Config okunamadı: {e}")
        return 1

    quality = config["quality"]
    output_folder = Path(config["output_folder"])
    output_playlist = config["output_playlist"]
    default_resolution = config.get("resolution", "1280x720")
    default_bandwidth = config.get("bandwidth", "1280000")

    output_folder.mkdir(parents=True, exist_ok=True)

    # Eski M3U8 dosyalarını temizle
    for old_file in output_folder.glob("*.m3u8"):
        if old_file.name != output_playlist:
            old_file.unlink()
    
    # Ana playlist için satırlar
    master_playlist_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    
    success_count = 0
    failed_channels = []

    for index, channel in enumerate(config["channels"], start=1):
        name = channel.get("name", f"Kanal {index}")
        channel_url = channel.get("url", "")

        print(f"\n🔄 [{index}/{len(config['channels'])}] {name}")

        if not channel_url:
            print(f"   ⚠️ URL yok, atlandı")
            failed_channels.append(name)
            continue

        # Kanal için resolution ve bandwidth ayarları
        resolution = default_resolution
        bandwidth = default_bandwidth
        
        if is_token_channel(channel_url):
            if is_atv_avrupa_name(name):
                resolution = "768x576"
                bandwidth = "800000"
            elif is_eurostar_name(name):
                resolution = "1920x1080"
                bandwidth = "3000000"
            elif is_show_turk_name(name):
                resolution = "1280x720"
                bandwidth = "1500000"
        
        # Stream URL'ini al
        stream_url = get_stream_url(channel, quality)
        
        if not stream_url:
            print(f"   ❌ Stream URL alınamadı")
            failed_channels.append(name)
            continue
        
        # Kanal için ayrı M3U8 dosyası oluştur
        channel_filename = safe_filename(name)
        channel_path = output_folder / channel_filename
        
        if create_channel_m3u8(stream_url, resolution, bandwidth, channel_path):
            print(f"   ✅ {channel_filename} oluşturuldu ({resolution})")
            
            # Ana playlist'e ekle
            master_playlist_lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={resolution}')
            master_playlist_lines.append(channel_filename)
            
            success_count += 1
        else:
            print(f"   ❌ Dosya oluşturulamadı")
            failed_channels.append(name)
        
        time.sleep(0.5)  # Rate limiting

    # Ana playlist dosyasını oluştur
    if master_playlist_lines:
        master_playlist_path = output_folder / output_playlist
        master_playlist_path.write_text("\n".join(master_playlist_lines), encoding="utf-8")
        
        print("\n" + "=" * 60)
        print(f"✅ İşlem tamamlandı!")
        print(f"📊 Başarılı: {success_count}/{len(config['channels'])} kanal")
        print(f"📁 Ana playlist: {master_playlist_path}")
        print(f"📄 Kanal dosyaları: {output_folder}/")
        
        # Kanal dosyalarını listele
        for file in sorted(output_folder.glob("*.m3u8")):
            if file.name != output_playlist:
                print(f"   - {file.name}")
        
        # Ana playlist içeriğini göster
        print("\n📄 Ana playlist içeriği:")
        for line in master_playlist_lines[:10]:
            print(f"   {line}")
        if len(master_playlist_lines) > 10:
            print(f"   ... ve {len(master_playlist_lines)-10} satır daha")
        
        if failed_channels:
            print(f"\n⚠️ Başarısız kanallar ({len(failed_channels)}):")
            for ch in failed_channels[:10]:
                print(f"   - {ch}")
    
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
