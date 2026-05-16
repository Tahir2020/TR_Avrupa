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


def is_token_channel(url: str) -> bool:
    """Token gerektiren kanal mı kontrol et"""
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
    """Netscape format cookies.txt dosyasını requests cookies dict formatına çevirir."""
    cookies: Dict[str, str] = {}
    path = Path(cookie_file)

    if not path.exists():
        print(f"   ℹ️ {cookie_file} bulunamadı, cookiesiz devam ediliyor")
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

        if cookies:
            print(f"   🍪 {len(cookies)} cookie yüklendi")
        else:
            print("   ⚠️ cookies.txt var ama okunabilir cookie bulunamadı")

    except Exception as e:
        print(f"   ⚠️ Cookie okuma hatası: {e}")

    return cookies


def get_atv_avrupa_stream() -> Optional[str]:
    """ATV Avrupa 576p - cookies.txt destekli otomatik token alıcı."""
    headers = {
        "X-isApp": "1",
        "X-Rand": str(int(time.time() * 1000)),
        "Origin": "https://www.atvavrupa.tv",
        "Referer": "https://www.atvavrupa.tv/",
        "User-Agent": CHROME_UA,
        "Accept": "*/*",
        "Accept-Language": "tr,en-US;q=0.9,en;q=0.8,de;q=0.7",
    }

    stream_url = "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa_576p.m3u8"
    encoded = urllib.parse.quote(stream_url)
    token_url = (
        "https://securevideotoken.tmgrup.com.tr/webtv/secure"
        f"?{random.randint(1, 1000000)}&url={encoded}&url2={encoded}"
    )

    cookies = load_netscape_cookies()

    try:
        response = requests.get(
            token_url,
            headers=headers,
            cookies=cookies if cookies else None,
            timeout=15,
        )

        print(f"   ATV token status: {response.status_code}")
        response.raise_for_status()
        data = response.json()

        if data.get("Success") and data.get("Url"):
            token_url_result = data.get("Url")
            print("   ✅ ATV Avrupa stream alındı")
            return token_url_result

        print(f"   ❌ ATV Avrupa token alınamadı: {data}")
        return None

    except Exception as e:
        print(f"   ❌ ATV Avrupa hatası: {e}")
        return None


def get_eurostar_stream() -> Optional[str]:
    """EuroStar 1080p - HTML'den token çek."""
    headers = {
        "User-Agent": CHROME_UA,
        "Accept": "text/html,application/xhtml+xml",
    }

    page_url = "https://www.eurostartv.com.tr/canli-izle"

    try:
        response = requests.get(page_url, headers=headers, timeout=15)
        html = response.text

        pattern = r"var liveUrl = 'https://dygvideo\.dygdigital\.com/live/hls/staravrupa\?token=([a-f0-9]+)';"
        match = re.search(pattern, html)

        if not match:
            print("   ❌ EuroStar token HTML'de bulunamadı")
            return None

        token = match.group(1)
        token_url = f"https://dygvideo.dygdigital.com/live/hls/staravrupa?token={token}"

        headers2 = {
            "Origin": "https://www.eurostartv.com.tr",
            "Referer": "https://www.eurostartv.com.tr/",
            "User-Agent": CHROME_UA,
        }

        response2 = requests.get(token_url, headers=headers2, allow_redirects=False, timeout=10)

        if response2.status_code == 302:
            master_url = response2.headers.get("Location")
            if not master_url:
                print("   ❌ EuroStar Location header boş")
                return None

            match = re.match(r"(.*/)live\.m3u8\?(.*)", master_url)
            if match:
                stream_url = f"{match.group(1)}live_1080p3000000kbps/index.m3u8?{match.group(2)}"
                print("   ✅ EuroStar 1080p stream alındı")
                return stream_url

            print("   ✅ EuroStar master URL alındı")
            return master_url

        print(f"   ❌ EuroStar redirect alınamadı: {response2.status_code}")
        return None

    except Exception as e:
        print(f"   ❌ EuroStar hatası: {e}")
        return None


def get_show_turk_stream() -> Optional[str]:
    """Show Türk - otomatik token alıcı."""
    url = "https://www.showturk.com.tr/canli-yayin"
    pattern = r"playlist\.m3u8\?e=(\d+)&st=([^\"\s&]+)"

    headers = {
        "User-Agent": CHROME_UA,
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        html = response.text
        match = re.search(pattern, html)

        if match:
            e, st = match.groups()
            stream_url = f"https://ciner-live.ercdn.net/showturk/playlist.m3u8?e={e}&st={st}&tv=1"
            print("   ✅ Show Türk stream alındı")
            return stream_url

        print("   ❌ Show Türk token bulunamadı")
        return None

    except Exception as e:
        print(f"   ❌ Show Türk hatası: {e}")
        return None


def get_youtube_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    """YouTube'dan stream URL alır"""
    cmd = [
        "yt-dlp",
        "-g",
        "--cookies", COOKIE_FILE,
        "--js-runtimes", "deno",
        "--remote-components", "ejs:github",
        "--extractor-args", "youtube:player_client=default",
        "-f", quality,
        youtube_url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        
        for line in lines:
            if "manifest" in line or ".m3u8" in line:
                return line

        if lines:
            return lines[0]

        return None

    except subprocess.CalledProcessError as e:
        print(f"   ❌ yt-dlp hatası: {e.stderr[:200]}")
        return None
    except Exception as e:
        print(f"   ❌ Hata: {e}")
        return None


def get_stream_url(channel: Dict, quality: str) -> Optional[str]:
    """Kanal tipine göre stream URL'sini alır"""
    channel_name = channel.get("name", "")
    channel_url = channel.get("url", "")

    print(f"   📍 URL: {channel_url[:80]}...")

    # Token gerektiren kanallar
    if is_token_channel(channel_url):
        if is_atv_avrupa_name(channel_name):
            print("   🔐 ATV Avrupa token alınıyor...")
            return get_atv_avrupa_stream()
        
        elif is_eurostar_name(channel_name):
            print("   🔐 EuroStar token alınıyor...")
            return get_eurostar_stream()
        
        elif is_show_turk_name(channel_name):
            print("   🔐 Show Türk token alınıyor...")
            return get_show_turk_stream()
        
        else:
            print(f"   ⚠️ Token handler bulunamadı")
            return None
    
    # Direkt M3U8 linki
    elif ".m3u8" in channel_url.lower():
        print("   🔗 Direkt M3U8 linki")
        return channel_url
    
    # YouTube linki
    elif "youtube.com" in channel_url or "youtu.be" in channel_url:
        print("   🎬 YouTube stream alınıyor...")
        return get_youtube_stream_url(channel_url, quality)
    
    else:
        print(f"   ⚠️ Bilinmeyen format")
        return None


def main() -> int:
    print("=" * 60)
    print("🎬 TV Kanalları HLS Playlist Oluşturucu")
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

    output_folder.mkdir(parents=True, exist_ok=True)

    # SADECE HLS MASTER PLAYLIST formatında çıktı - hiçbir logo/metadata yok
    playlist_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    
    success_count = 0
    failed_channels = []

    for index, channel in enumerate(config["channels"], start=1):
        name = channel.get("name", f"Kanal {index}")
        channel_url = channel.get("url", "")

        if not channel_url:
            print(f"\n⚠️ [{index}/{len(config['channels'])}] {name}: URL yok")
            failed_channels.append(name)
            continue

        print(f"\n🔄 [{index}/{len(config['channels'])}] {name}")
        
        stream_url = get_stream_url(channel, quality)

        if not stream_url:
            print(f"   ❌ Stream alınamadı")
            failed_channels.append(name)
            continue

        # Sade ve temiz HLS master playlist entry
        # Örnek: #EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720
        resolution = config.get("resolution", "1280x720")
        bandwidth = config.get("bandwidth", "1280000")
        
        playlist_lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={resolution}')
        playlist_lines.append(stream_url)
        
        print(f"   ✅ Başarılı - {resolution}")
        success_count += 1
        
        time.sleep(0.5)  # Rate limiting

    # Playlist dosyasını yaz
    output_path = output_folder / output_playlist
    output_path.write_text("\n".join(playlist_lines), encoding="utf-8")
    
    print("\n" + "=" * 60)
    print(f"✅ İşlem tamamlandı!")
    print(f"📊 Başarılı: {success_count}/{len(config['channels'])} kanal")
    print(f"📁 Çıktı: {output_path}")
    print(f"📦 Dosya boyutu: {output_path.stat().st_size} byte")
    
    if failed_channels:
        print(f"\n⚠️ Başarısız kanallar ({len(failed_channels)}):")
        for ch in failed_channels[:10]:
            print(f"   - {ch}")
        if len(failed_channels) > 10:
            print(f"   ... ve {len(failed_channels)-10} kanal daha")
    
    # Çıktının ilk 20 satırını göster
    print("\n📄 Oluşan playlist (ilk 20 satır):")
    lines = playlist_lines[:20]
    for line in lines:
        if len(line) > 100:
            print(f"   {line[:100]}...")
        else:
            print(f"   {line}")
    
    print("\n✅ Tüm logolar ve metadata TEMİZLENDİ!")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
