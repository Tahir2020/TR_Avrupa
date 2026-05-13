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
    Cookies OLMADAN çalışır - daha güvenilir
    """
    # yt-dlp komutu - cookies'siz
    cmd = [
        'yt-dlp',
        '-g',
        '--no-check-certificate',
        '--extractor-args', 'youtube:player_client=android,web',
        '--no-cache-dir',
        '-f', quality,
        youtube_url
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            # Hata detayını göster
            error_msg = result.stderr.strip() if result.stderr else "Bilinmeyen hata"
            if "Sign in to confirm" in error_msg:
                print(f"   ⚠️ YouTube oturum gerektiriyor (public olmayan yayın)")
            elif "Video unavailable" in error_msg:
                print(f"   ⚠️ Video mevcut değil veya yayında değil")
            else:
                print(f"   ❌ Hata: {error_msg[:100]}")
            return None
            
        # Çıktıyı al
        output = result.stdout.strip()
        if not output:
            print(f"   ❌ Boş çıktı")
            return None
            
        # İlk satırı al (genelde video manifest)
        stream_url = output.splitlines()[0]
        
        # Geçerli bir m3u8 URL'si mi kontrol et
        if stream_url and ('.m3u8' in stream_url or 'manifest' in stream_url):
            return stream_url
        else:
            print(f"   ⚠️ Geçersiz URL formatı: {stream_url[:50]}...")
            return None
            
    except subprocess.TimeoutExpired:
        print(f"   ⏱️ Zaman aşımı (60 sn)")
        return None
    except Exception as e:
        print(f"   ❌ Beklenmeyen hata: {str(e)[:100]}")
        return None


def save_channel_m3u(channel: Dict, stream_url: str) -> bool:
    """Her kanal için ayrı M3U dosyası oluşturur"""
    if not stream_url:
        return False
    
    # Output dizinini oluştur
    os.makedirs('output', exist_ok=True)
    
    # Güvenli dosya adı
    safe_name = channel['channel_name'].replace(' ', '_').replace('/', '_').replace(':', '').replace('?', '')
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
        print(f"   ❌ Dosya yazma hatası: {e}")
        return False


def save_master_playlist(channels_data: List[Dict], output_file: str) -> None:
    """Ana playlist'i gruplandırarak oluşturur"""
    # Gruplara ayır
    groups = {}
    for ch in channels_data:
        group = ch['group_title']
        if group not in groups:
            groups[group] = []
        groups[group].append(ch)
    
    # M3U içeriği oluştur
    m3u_content = "#EXTM3U\n"
    m3u_content += f"# Playlist oluşturulma: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    m3u_content += f"# Toplam kanal: {len(channels_data)}\n"
    m3u_content += f"# Çalışan kanal: {sum(1 for ch in channels_data if ch.get('stream_url'))}\n\n"
    
    for group_name, channels in sorted(groups.items()):
        m3u_content += f"\n# === {group_name.upper()} GRUBU ({len(channels)} kanal) ===\n"
        for ch in channels:
            if ch.get('stream_url'):
                m3u_content += f'#EXTINF:-1 tvg-id="{ch["channel_name"].lower().replace(" ", "")}" tvg-name="{ch["channel_name"]}" tvg-logo="{ch["channel_logo"]}" group-title="{ch["group_title"]}", {ch["channel_name"]}\n'
                m3u_content += f'{ch["stream_url"]}\n'
            else:
                m3u_content += f'#EXTINF:-1 group-title="{ch["group_title"]}", ❌ {ch["channel_name"]} (YAYINDA DEĞİL)\n'
                m3u_content += f'# STREAM URL ALINAMADI - YouTube kanalı canlı değil veya erişim kısıtlı\n'
    
    # Dosyaya yaz
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(m3u_content)
    
    print(f"\n✅ Master playlist oluşturuldu: {output_file}")


def process_channel(channel: Dict, quality: str) -> Dict:
    """Tek bir kanalı işler"""
    print(f"🔄 {channel['channel_name']:25} | {channel['group_title']:15}", end=" ", flush=True)
    
    stream_url = get_stream_url(channel['youtube_url'], quality)
    
    result = channel.copy()
    result['stream_url'] = stream_url
    
    if stream_url:
        if save_channel_m3u(channel, stream_url):
            print("✅")
        else:
            print("⚠️ (kayıt hatası)")
    else:
        print("❌")
    
    return result


def main():
    print("=" * 70)
    print("🎬 TÜRKİYE IPTV - 24 KANAL YAYIN GÜNCELLEYİCİ (Cookies'siz)")
    print("=" * 70)
    
    config = load_config()
    channels = config['channels']
    quality = config['quality']
    
    print(f"\n📡 Toplam kanal: {len(channels)}")
    print(f"🎯 Kalite: {quality}")
    print(f"🍪 Cookies: ❌ Kullanılmıyor")
    print(f"🚀 Başlıyor...\n")
    
    start_time = datetime.now()
    processed = []
    
    # Paralel işleme (max 3)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(process_channel, ch, quality): ch for ch in channels}
        for future in as_completed(futures):
            try:
                processed.append(future.result())
            except Exception as e:
                ch = futures[future]
                print(f"❌ {ch['channel_name']} kritik hata: {e}")
                ch_copy = ch.copy()
                ch_copy['stream_url'] = None
                processed.append(ch_copy)
    
    # Master playlist oluştur
    save_master_playlist(processed, 'playerlist.m3u')
    
    # İstatistikler
    elapsed = (datetime.now() - start_time).total_seconds()
    success = sum(1 for ch in processed if ch['stream_url'])
    
    print("\n" + "=" * 70)
    print("📊 TARAMA RAPORU")
    print("=" * 70)
    print(f"✅ Başarılı: {success}/{len(processed)} kanal")
    print(f"❌ Başarısız: {len(processed) - success}/{len(processed)} kanal")
    print(f"⏱️  Süre: {elapsed:.1f} saniye")
    
    # Grup istatistikleri
    print("\n📺 GRUP BAZLI DURUM:")
    groups = {}
    for ch in processed:
        g = ch['group_title']
        if g not in groups:
            groups[g] = {'total': 0, 'ok': 0, 'channels': []}
        groups[g]['total'] += 1
        if ch['stream_url']:
            groups[g]['ok'] += 1
            groups[g]['channels'].append(ch['channel_name'])
    
    for g, stats in sorted(groups.items()):
        status = "✅" if stats['ok'] == stats['total'] else "⚠️"
        print(f"   {status} {g:15}: {stats['ok']:2}/{stats['total']}")
        if stats['ok'] < stats['total'] and stats['channels']:
            print(f"      Çalışan: {', '.join(stats['channels'][:3])}")
    
    # Çalışan kanalları göster
    if success > 0:
        print(f"\n🎉 {success} kanal başarıyla eklendi!")
        print("📺 Playlist: playerlist.m3u")
    else:
        print("\n⚠️ Hiçbir kanal çalışmıyor! Muhtemel nedenler:")
        print("   1. YouTube kanalları şu an canlı yayında değil")
        print("   2. YouTube coğrafi kısıtlama uyguluyor")
        print("   3. yt-dlp güncel değil (güncellemek için: pip install -U yt-dlp)")
    
    sys.exit(0 if success > 0 else 1)


if __name__ == "__main__":
    main()
