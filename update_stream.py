#!/usr/bin/env python3

import json
import re
import subprocess
import sys
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

CONFIG_FILE = "config.json"


def load_config() -> Dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    if "channels" not in config or not isinstance(config["channels"], list):
        raise ValueError("config.json içinde 'channels' listesi bulunamadı.")

    if not config["channels"]:
        raise ValueError("config.json içinde kanal listesi boş.")

    config.setdefault("quality", "best[height<=1080][fps<=50]/best")
    config.setdefault("output_folder", "playlist")
    config.setdefault("output_playlist", "playerlist.m3u")
    return config


def safe_filename(name: str) -> str:
    replacements = {
        "ç": "c", "Ç": "C",
        "ğ": "g", "Ğ": "G",
        "ı": "i", "İ": "I",
        "ö": "o", "Ö": "O",
        "ş": "s", "Ş": "S",
        "ü": "u", "Ü": "U",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)

    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return f"{name or 'channel'}.m3u"


def is_direct_m3u8(url: str) -> bool:
    clean = url.lower().split("?", 1)[0]
    return clean.endswith(".m3u8")


def get_atv_avrupa_token() -> Optional[str]:
    """ATV Avrupa 576p token al - Düzeltilmiş versiyon"""
    headers = {
        "X-isApp": "1",
        "X-Rand": str(int(datetime.now().timestamp() * 1000)),
        "Origin": "https://www.atvavrupa.tv",
        "Referer": "https://www.atvavrupa.tv/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # Alternatif URL'leri dene
    urls = [
        "https://securevideotoken.tmgrup.com.tr/webtv/secure?759173&url=https://trkvz-live.ercdn.net/atvavrupa/atvavrupa_576p.m3u8&url2=https://trkvz-live.ercdn.net/atvavrupa/atvavrupa_576p.m3u8",
        "https://securevideotoken.tmgrup.com.tr/webtv/secure?url=https://trkvz-live.ercdn.net/atvavrupa/atvavrupa.m3u8",
        "https://securevideotoken.tmgrup.com.tr/webtv/secure?759173&url=https://trkvz-live.ercdn.net/atvavrupa/atvavrupa.m3u8"
    ]
    
    for url in urls:
        try:
            print(f"   Denenen URL: {url[:80]}...")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("Success") and data.get("Url"):
                    print(f"   ✅ Token alındı (URL: {url[:50]}...)")
                    return data.get("Url")
                elif data.get("url"):
                    return data.get("url")
        except Exception as e:
            print(f"   ❌ Hata: {str(e)[:50]}")
            continue
    
    print("   ❌ Tüm URL'ler denendi, token alınamadı")
    return None


def get_star_avrupa_token() -> Optional[str]:
    """Star Avrupa / EuroStar token al - Düzeltilmiş versiyon"""
    headers = {
        "Origin": "https://www.eurostartv.com.tr",
        "Referer": "https://www.eurostartv.com.tr/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # Farklı tokenları dene
    tokens = [
        "1ef7e00fe53c90636a8da88c4614fac65b9aecc277e0d0ea",
        "",  # Boş token dene
        "latest"  # Latest parametresi dene
    ]
    
    for token in tokens:
        if token:
            url = f"https://dygvideo.dygdigital.com/live/hls/staravrupa?token={token}"
        else:
            url = "https://dygvideo.dygdigital.com/live/hls/staravrupa"
        
        try:
            print(f"   Denenen URL: {url[:80]}...")
            response = requests.get(url, headers=headers, allow_redirects=False, timeout=10)
            
            if response.status_code == 302:
                location = response.headers.get("Location")
                if location:
                    print(f"   ✅ Token alındı (status: 302)")
                    return location
            elif response.status_code == 200:
                # Direkt m3u8 gelmiş olabilir
                if ".m3u8" in response.text:
                    print(f"   ✅ Direkt m3u8 alındı")
                    return response.text.strip()
        except Exception as e:
            print(f"   ❌ Hata: {str(e)[:50]}")
            continue
    
    # Alternatif: Sayfadan çekmeyi dene
    try:
        print("   🔄 Sayfadan token aranıyor...")
        page_url = "https://www.eurostartv.com.tr"
        page_response = requests.get(page_url, headers=headers, timeout=10)
        
        # Sayfada m3u8 linki ara
        m3u8_pattern = r'https?://[^"\s]+\.m3u8[^"\s]*'
        matches = re.findall(m3u8_pattern, page_response.text)
        
        for match in matches:
            if "staravrupa" in match or "eurostar" in match:
                print(f"   ✅ Sayfadan m3u8 bulundu")
                return match
    except Exception as e:
        print(f"   ❌ Sayfa hatası: {str(e)[:50]}")
    
    print("   ❌ Tüm yöntemler denendi, token alınamadı")
    return None


def get_show_turk_token() -> Optional[str]:
    """Show Türk token al (sayfadan regex ile)"""
    url = "https://www.showturk.com.tr/canli-yayin"
    pattern = r'playlist\.m3u8\?e=(\d+)&st=([^"\s&]+)'
    
    try:
        response = requests.get(url, timeout=10)
        match = re.search(pattern, response.text)
        if match:
            e, st = match.groups()
            return f"https://ciner-live.ercdn.net/showturk/playlist.m3u8?e={e}&st={st}&tv=1"
        return None
    except Exception as e:
        print(f"❌ Show Türk token hatası: {e}")
        return None


def get_youtube_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    cmd = [
        "yt-dlp",
        "-g",
        "--cookies", "cookies.txt",
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
        print("❌ yt-dlp hatası:")
        print(e.stderr)
        return None
    except Exception as e:
        print(f"❌ Hata: {e}")
        return None


def get_stream_url(channel: Dict, quality: str) -> Optional[str]:
    """Kanal tipine göre stream URL'sini al"""
    
    # Özel token gerektiren kanallar
    channel_name = channel.get("name", "")
    
    if "ATV Avrupa" in channel_name:
        print("🔐 ATV Avrupa için token alınıyor...")
        return get_atv_avrupa_token()
    
    if "Star Avrupa" in channel_name or "Euro Star" in channel_name:
        print("🔐 Star Avrupa/EuroStar için token alınıyor...")
        return get_star_avrupa_token()
    
    if "Show Türk" in channel_name:
        print("🔐 Show Türk için token alınıyor...")
        return get_show_turk_token()
    
    # Normal URL veya YouTube
    url = channel.get("url") or channel.get("youtube_url")
    
    if not url:
        return None

    if is_direct_m3u8(url):
        print("🔗 Direkt m3u8 linki kullanılıyor")
        return url

    print("🎬 YouTube stream alınıyor...")
    return get_youtube_stream_url(url, quality)


def create_extinf(channel: Dict, stream_url: str) -> str:
    name = channel["name"]
    logo = channel.get("logo", "")
    group = channel.get("group", "Genel")
    tvg_id = channel.get("tvg_id", safe_filename(name).replace(".m3u", "").lower())

    return (
        f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" '
        f'tvg-logo="{logo}" group-title="{group}",{name}\n'
        f'{stream_url}\n'
    )


def write_single_channel_file(channel: Dict, stream_url: str, output_folder: Path) -> Path:
    output_folder.mkdir(parents=True, exist_ok=True)
    filename = channel.get("m3u_file") or safe_filename(channel["name"])
    path = output_folder / filename

    content = "#EXTM3U\n" + create_extinf(channel, stream_url)
    path.write_text(content, encoding="utf-8")
    return path


def write_main_playlist(entries: List[str], output_folder: Path, output_playlist: str) -> Path:
    output_folder.mkdir(parents=True, exist_ok=True)
    path = output_folder / output_playlist
    content = "#EXTM3U\n" + "\n".join(entries)
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    print("=" * 60)
    print("🎬 TV Kanalları M3U Güncelleyici (Token Desteği Eklendi)")
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

    for old_file in output_folder.glob("*.m3u"):
        old_file.unlink()

    playlist_entries: List[str] = []
    failed_channels: List[str] = []

    for index, channel in enumerate(config["channels"], start=1):
        name = channel.get("name", f"Kanal {index}")

        if not (channel.get("url") or channel.get("youtube_url")):
            print(f"⚠️ {name}: url/youtube_url yok, atlandı")
            failed_channels.append(name)
            continue

        print(f"\n🔄 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [{index}/{len(config['channels'])}] {name} taranıyor...")
        stream_url = get_stream_url(channel, quality)

        if not stream_url:
            print(f"❌ {name}: Stream/Manifest URL alınamadı")
            failed_channels.append(name)
            continue

        single_file = write_single_channel_file(channel, stream_url, output_folder)
        playlist_entries.append(create_extinf(channel, stream_url))
        print(f"✅ {name}: {single_file} oluşturuldu")

    if playlist_entries:
        main_playlist = write_main_playlist(playlist_entries, output_folder, output_playlist)
        print(f"\n✅ Toplu liste oluşturuldu: {main_playlist}")
        print(f"✅ Başarılı kanal sayısı: {len(playlist_entries)}")
    else:
        print("\n❌ Hiçbir kanal için link alınamadı")
        return 1

    if failed_channels:
        print("\n⚠️ Alınamayan kanallar:")
        for channel_name in failed_channels:
            print(f"- {channel_name}")

    print("\n📄 Oluşan M3U dosyaları:")
    for file in sorted(output_folder.glob("*.m3u")):
        print(f"- {file}")

    print("\n✅ İşlem tamamlandı")
    return 0


if __name__ == "__main__":
    sys.exit(main())
