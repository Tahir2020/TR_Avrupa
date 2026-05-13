#!/usr/bin/env python3

import subprocess
import json
import sys
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional


def load_config() -> Dict:
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ config.json bulunamadı!")
        sys.exit(1)


def get_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    """
    YouTube canlı yayın URL'sinden m3u8 manifest adresini alır
    """
    # Base komut
    cmd = [
        'yt-dlp',
        '-g',
        '--no-check-certificate',
        '--extractor-args', 'youtube:player_client=web',
        '--no-cache-dir',
        '-f', quality,
        youtube_url
    ]
    
    # Cookie varsa ekle
    cookie_file = 'cookies.txt'
    if os.path.exists(cookie_file) and os.path.getsize(cookie_file) > 100:
        cmd.insert(2, '--cookies')
        cmd.insert(3, cookie_file)
        print("🍪", end=" ", flush=True)
    else:
        print("🔓", end=" ", flush=True)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=90
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else ""
            
            if "Sign in to confirm" in error_msg:
                print("🔐 Oturum gerekli")
            elif "Video unavailable" in error_msg:
                print("📺 Yayında değil")
            elif "Private video" in error_msg:
                print("🔒 Gizli video")
            elif "not made this video available" in error_msg:
                print("🌍 Coğrafi kısıtlama")
            elif "cookies" in error_msg.lower():
                print("🍪 Cookie geçersiz")
            else:
                short_err = error_msg.split('\n')[0][:50] if error_msg else "Hata"
                print(f"❌ {short_err}")
            return None
            
        output = result.stdout.strip()
        if not output:
            print("❌ Boş çıktı")
            return None
            
        stream_url = output.splitlines()[0]
        
        if stream_url and ('.m3u8' in stream_url or 'googlevideo' in stream_url):
            return stream_url
        else:
            print("⚠️ Geçersiz URL")
            return None
            
    except subprocess.TimeoutExpired:
        print("⏱️ Zaman aşımı")
        return None
    except Exception as e:
        print(f"❌ {str(e)[:40]}")
        return None


def save_channel_m3u(channel: Dict, stream_url: str) -> bool:
    if not stream_url:
        return False
    
    os.makedirs('output', exist_ok=True)
    
    safe_name = channel['channel_name'].replace(' ', '_').replace('/', '_').replace(':', '').replace('?', '').replace('(', '').replace(')', '')
    filename = os.path.join('output', f"{safe_name}.m3u")
    
    m3u_content = f"""#EXTM3U
#EXTINF:-1 tvg-id="{safe_name.lower()}" tvg-name="{channel['channel_name']}" tvg-logo="{channel['channel_logo']}" group-title="{channel['group_title']}", {channel['channel_name']}
{stream_url}
"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(m3u_content)
        return True
    except Exception as e:
        return False


def save_master_playlist(channels_data: List[Dict], output_file: str) -> None:
    groups = {}
    for ch in channels_data:
        group = ch['group_title']
        if group not in groups:
            groups[group] = []
        groups[group].append(ch)
    
    successful = sum(1 for ch in channels_data if ch.get('stream_url'))
    
    m3u_content = "#EXTM3U\n"
    m3u_content += f"# Playlist: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    m3u_content += f"# Toplam: {len(channels_data)} | Çalışan: {successful}\n\n"
    
    for group_name, channels in sorted(groups.items()):
        working = sum(1 for ch in channels if ch.get('stream_url'))
        m3u_content += f"\n# === {group_name.upper()} ({working}/{len(channels)}) ===\n"
        for ch in channels:
            if ch.get('stream_url'):
                m3u_content += f'#EXTINF:-1 tvg-name="{ch["channel_name"]}" tvg-logo="{ch["channel_logo"]}" group-title="{ch["group_title"]}", {ch["channel_name"]}\n'
                m3u_content += f'{ch["stream_url"]}\n'
            else:
                m3u_content += f'#EXTINF:-1 group-title="{ch["group_title"]}", ⚠️ {ch["channel_name"]}\n'
                m3u_content += f'# OFFLINE\n'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(m3u_content)


def process_channel(channel: Dict, quality: str) -> Dict:
    name = channel['channel_name'][:22]
    print(f"🔄 {name:22} | {channel['group_title']:10}", end=" ", flush=True)
    
    stream_url = get_stream_url(channel['youtube_url'], quality)
    
    result = channel.copy()
    result['stream_url'] = stream_url
    
    if stream_url:
        if save_channel_m3u(channel, stream_url):
            print("✅")
        else:
            print("⚠️")
    else:
        pass  # Hata zaten print edildi
    
    return result


def main():
    print("=" * 70)
    print("🎬 TÜRKİYE IPTV - CANLI YAYIN GÜNCELLEYİCİ")
    print("=" * 70)
    
    config = load_config()
    channels = config['channels']
    quality = config['quality']
    
    cookie_status = "✅ Var" if os.path.exists('cookies.txt') and os.path.getsize('cookies.txt') > 100 else "❌ Yok"
    
    print(f"\n📡 Toplam kanal: {len(channels)}")
    print(f"🍪 Cookies: {cookie_status}")
    print(f"🚀 Başlıyor...\n")
    
    if cookie_status == "❌ Yok":
        print("⚠️ UYARI: cookies.txt bulunamadı!")
        print("💡 YouTube artık cookies gerektiriyor.")
        print("💡 'get_cookies.py' ile tarayıcınızdan cookies alın.\n")
    
    start_time = datetime.now()
    processed = []
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(process_channel, ch, quality): ch for ch in channels}
        for future in as_completed(futures):
            try:
                processed.append(future.result())
            except Exception as e:
                ch = futures[future]
                print(f"❌ {ch['channel_name']}: {e}")
                ch_copy = ch.copy()
                ch_copy['stream_url'] = None
                processed.append(ch_copy)
    
    save_master_playlist(processed, 'playerlist.m3u')
    
    elapsed = (datetime.now() - start_time).total_seconds()
    success = sum(1 for ch in processed if ch['stream_url'])
    
    print("\n" + "=" * 70)
    print("📊 RAPOR")
    print("=" * 70)
    print(f"✅ Başarılı: {success}/{len(processed)} kanal")
    print(f"⏱️  Süre: {elapsed:.1f} saniye")
    
    if success == 0:
        print("\n⚠️ HİÇBİR KANAL ÇALIŞMIYOR!")
        print("\nÇÖZÜM:")
        print("1. YouTube'da oturum açın (chrome/firefox)")
        print("2. pip install browser-cookie3")
        print("3. python get_cookies.py")
        print("4. cookies.txt oluştuktan sonra tekrar çalıştırın")
    
    sys.exit(0 if success > 0 else 1)


if __name__ == "__main__":
    main()
