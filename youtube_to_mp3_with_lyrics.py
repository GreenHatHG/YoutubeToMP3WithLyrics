#!/usr/bin/env python3

import os
import subprocess
import sys
import eyed3
import argparse
import re
import shutil
from typing import List, Tuple, Dict, Optional
from pathlib import Path

class Config:
    """Centralized configuration management"""
    def __init__(self, args):
        self.url = args.url
        self.merge_mode = args.merge
        self.audio_path = args.audio
        self.subtitle_path = args.subtitle
        self.output_dir = Path(args.output or "./final_mp3s")
        self.source_dir = Path(args.source_dir or "./source_files")
        self.start_time = args.start
        self.end_time = args.end
        self.lang = args.lang or "en"
        self.enhance_stereo = args.enhance_stereo
        self.no_cleanup = args.no_cleanup
        
        # Ensure directories exist
        self.output_dir.mkdir(exist_ok=True)
        self.source_dir.mkdir(exist_ok=True)

class SubtitleProcessor:
    """Subtitle processor"""
    
    @staticmethod
    def parse_time(time_str: str) -> float:
        """Parse time string"""
        if '.' not in time_str:
            time_str += '.000'
        parts = time_str.strip().split(':')
        
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
        elif len(parts) == 2:
            h, m, s = 0, int(parts[0]), float(parts[1])
        else:
            raise ValueError(f"Unable to parse time format: {time_str}")
        
        return h * 3600 + m * 60 + s
    
    @staticmethod
    def seconds_to_lrc_time(seconds: float) -> str:
        """Convert seconds to LRC time format"""
        if seconds < 0:
            seconds = 0
        minutes = int(seconds // 60)
        secs = seconds % 60
        centiseconds = int((secs * 100) % 100)
        return f"[{minutes:02d}:{int(secs):02d}.{centiseconds:02d}]"
    
    @classmethod
    def srt_to_lrc(cls, srt_path: str, lrc_path: str, start_time: str = None, end_time: str = None):
        """Convert SRT to LRC"""
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read().lstrip('\ufeff')
        
        # Parse SRT
        subtitles = []
        time_pattern = r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})'
        
        for block in content.strip().split('\n\n'):
            lines = block.strip().split('\n')
            if len(lines) < 3:
                continue
            
            time_match = re.search(time_pattern, lines[1])
            if time_match:
                try:
                    start_sec = cls.parse_time(time_match.group(1).replace(',', '.'))
                    text = ' '.join(lines[2:]).strip()
                    text = re.sub(r'<[^>]+>', '', text).strip()  # Remove HTML tags
                    
                    if text:
                        subtitles.append((start_sec, text))
                except ValueError:
                    continue
        
        # Sort and deduplicate
        subtitles = sorted(set(subtitles), key=lambda x: x[0])
        
        # Time filtering
        offset = 0
        if start_time and end_time:
            start_sec = cls.parse_time(start_time)
            end_sec = cls.parse_time(end_time)
            subtitles = [(s, t) for s, t in subtitles if start_sec <= s <= end_sec]
            offset = start_sec
        
        # Generate LRC
        lrc_lines = [f"{cls.seconds_to_lrc_time(s - offset)}{t}" 
                    for s, t in subtitles if s - offset >= 0]
        
        with open(lrc_path, 'w', encoding='utf-8') as f:
            f.write("[by:youtube_to_mp3_optimized.py]\n" + '\n'.join(lrc_lines))

class AudioProcessor:
    """Audio processor"""
    
    @staticmethod
    def run_cmd(cmd: List[str], quiet: bool = False) -> str:
        """Execute command"""
        if not quiet:
            print(f"▶️ {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if result.returncode != 0 and not quiet:
            print(f"❌ Command failed: {result.stderr}")
            sys.exit(1)
        
        return result.stdout + result.stderr
    
    @classmethod
    def enhance_stereo(cls, audio_path: str):
        """Enhance stereo audio"""
        temp_path = f"{audio_path}.temp"
        filter_chain = "extrastereo=m=2.5,haas=level_in=1:level_out=1:side_gain=0.8,volume=0.7"
        
        cmd = ["ffmpeg", "-i", audio_path, "-af", filter_chain, 
               "-ac", "2", "-ar", "44100", "-b:a", "192k", "-y", temp_path]
        
        cls.run_cmd(cmd)
        os.replace(temp_path, audio_path)
        print("✅ Stereo enhancement completed")
    
    @classmethod
    def convert_to_mp3(cls, input_path: str, output_path: str, enhance: bool = False, 
                      start_time: str = None, end_time: str = None):
        """Convert to MP3"""
        if Path(input_path).suffix.lower() == '.mp3' and not start_time and not end_time:
            shutil.copy2(input_path, output_path)
        else:
            cmd = ["ffmpeg", "-i", input_path, "-vn", "-acodec", "mp3", 
                   "-ab", "192k", "-ar", "44100"]
            
            # Add time range if specified
            if start_time:
                cmd.extend(["-ss", start_time])
            if end_time:
                cmd.extend(["-to", end_time])
            
            cmd.extend(["-y", output_path])
            cls.run_cmd(cmd)
        
        if enhance:
            cls.enhance_stereo(output_path)

class YouTubeDownloader:
    """YouTube downloader"""
    
    @staticmethod
    def run_cmd(cmd: List[str]) -> str:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Command failed: {result.stderr}")
        return result.stdout.strip()
    
    @classmethod
    def get_metadata(cls, url: str) -> Dict[str, str]:
        """Get video metadata"""
        title = cls.run_cmd(["yt-dlp", "--get-title", url])
        video_id = cls.run_cmd(["yt-dlp", "--get-id", url])
        title = re.sub(r'[\\/*?:"<>|]', '_', title)
        return {"id": video_id, "title": title}
    
    @classmethod
    def get_subtitles(cls, url: str) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Get available subtitles"""
        output = cls.run_cmd(["yt-dlp", "--list-subs", url])
        manual_subs, auto_subs = {}, {}
        
        parsing_manual = parsing_auto = False
        for line in output.splitlines():
            line = line.strip()
            if "Available subtitles for" in line:
                parsing_manual, parsing_auto = True, False
            elif "Available automatic captions for" in line:
                parsing_manual, parsing_auto = False, True
            elif line and not line.startswith(('language', 'id', '---')):
                match = re.match(r'^([a-zA-Z0-9._-]+)\s+(.+?)\s+(?:vtt|srt|ttml)', line)
                if match:
                    lang_code, lang_name = match.groups()
                    if parsing_manual:
                        manual_subs[lang_code] = lang_name.strip()
                    elif parsing_auto:
                        auto_subs[lang_code] = lang_name.strip()
        
        return manual_subs, auto_subs
    
    @classmethod
    def download(cls, url: str, output_dir: Path, video_id: str, lang: str, 
                start_time: str = None, end_time: str = None) -> bool:
        """Download audio and subtitles"""
        template = str(output_dir / f"{video_id}.%(ext)s")
        
        # Check subtitle availability
        manual_subs, auto_subs = cls.get_subtitles(url)
        use_auto = lang not in manual_subs
        
        if lang not in manual_subs and lang not in auto_subs:
            print(f"❌ Cannot find subtitles for language '{lang}'")
            return False
        
        # Build download command
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3"]
        
        if use_auto:
            cmd.extend(["--write-auto-sub", "--sub-lang", lang, "--sub-format", "srt"])
            print(f"⚠️ Using auto-generated subtitles: {lang}")
        else:
            cmd.extend(["--write-sub", "--sub-lang", lang, "--sub-format", "srt"])
            print(f"✅ Using manual subtitles: {lang}")
        
        if start_time and end_time:
            cmd.extend(["--download-sections", f"*{start_time}-{end_time}"])
        
        cmd.extend(["-o", template, url])
        
        try:
            cls.run_cmd(cmd)
            return True
        except Exception as e:
            print(f"❌ Download failed: {e}")
            return False

class LyricsEmbedder:
    """Lyrics embedder"""
    
    @staticmethod
    def embed_lyrics(mp3_path: str, lrc_path: str):
        """Embed LRC lyrics into MP3"""
        audiofile = eyed3.load(mp3_path)
        if not audiofile:
            raise IOError("Cannot load MP3 file")
        
        if not audiofile.tag:
            audiofile.initTag(version=eyed3.id3.ID3_V2_3)
        
        with open(lrc_path, 'r', encoding='utf-8') as f:
            lrc_text = f.read()
        
        audiofile.tag.lyrics.remove('')
        audiofile.tag.lyrics.set(lrc_text)
        audiofile.tag.save(version=eyed3.id3.ID3_V2_3, encoding='utf-8')

def merge_mode(config: Config):
    """Merge mode"""
    if not config.audio_path or not config.subtitle_path:
        sys.exit("❌ Merge mode requires --audio and --subtitle parameters")
    
    audio_path = Path(config.audio_path)
    subtitle_path = Path(config.subtitle_path)
    
    if not audio_path.exists() or not subtitle_path.exists():
        sys.exit("❌ Audio or subtitle file does not exist")
    
    # Generate output filename
    base_name = audio_path.stem
    output_mp3 = config.output_dir / f"{base_name}.mp3"
    source_mp3 = config.source_dir / f"{base_name}.mp3"
    source_lrc = config.source_dir / f"{base_name}.lrc"
    
    # Check if input audio is already in source_dir and is the same as target
    if audio_path.resolve() == source_mp3.resolve():
        print(f"✅ Audio file already in source directory: {audio_path}")
        # Apply stereo enhancement if requested
        if config.enhance_stereo:
            AudioProcessor.enhance_stereo(str(source_mp3))
    else:
        # Convert audio
        AudioProcessor.convert_to_mp3(str(audio_path), str(source_mp3), config.enhance_stereo,
                                     config.start_time, config.end_time)
    
    # Convert subtitles
    SubtitleProcessor.srt_to_lrc(str(subtitle_path), str(source_lrc), 
                                config.start_time, config.end_time)
    
    # Embed lyrics
    shutil.copy2(source_mp3, output_mp3)
    LyricsEmbedder.embed_lyrics(str(output_mp3), str(source_lrc))
    
    # Cleanup
    if not config.no_cleanup:
        source_mp3.unlink(missing_ok=True)
        source_lrc.unlink(missing_ok=True)
    
    print(f"✅ Merge completed: {output_mp3}")

def download_mode(config: Config):
    """Download mode"""
    if not config.url:
        sys.exit("❌ YouTube URL required")
    
    # Get video information
    metadata = YouTubeDownloader.get_metadata(config.url)
    video_id = metadata['id']
    title = metadata['title']
    
    # File paths
    final_mp3 = config.output_dir / f"{title} [{video_id}].mp3"
    source_mp3 = config.source_dir / f"{video_id}.mp3"
    source_srt = config.source_dir / f"{video_id}.{config.lang}.srt"
    source_lrc = config.source_dir / f"{video_id}.lrc"
    
    if final_mp3.exists():
        print(f"✅ File already exists: {final_mp3}")
        return
    
    # Download
    if not (source_mp3.exists() and source_srt.exists()):
        if not YouTubeDownloader.download(config.url, config.source_dir, video_id, 
                                        config.lang, config.start_time, config.end_time):
            sys.exit("❌ Download failed")
    
    # Stereo enhancement
    if config.enhance_stereo and source_mp3.exists():
        AudioProcessor.enhance_stereo(str(source_mp3))
    
    # Convert subtitles
    if not source_lrc.exists():
        SubtitleProcessor.srt_to_lrc(str(source_srt), str(source_lrc), 
                                   config.start_time, config.end_time)
    
    # Embed lyrics
    shutil.copy2(source_mp3, final_mp3)
    LyricsEmbedder.embed_lyrics(str(final_mp3), str(source_lrc))
    
    # Cleanup
    if not config.no_cleanup:
        for f in [source_mp3, source_srt, source_lrc]:
            f.unlink(missing_ok=True)
    
    print(f"✅ Completed: {final_mp3}")

def main():
    parser = argparse.ArgumentParser(description="YouTube audio download and lyrics embedding tool")
    
    # Main parameters
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs='?', help="YouTube video URL")
    group.add_argument("--merge", action="store_true", help="Merge mode")
    
    # Merge mode parameters
    parser.add_argument("--audio", help="Audio file path")
    parser.add_argument("--subtitle", help="Subtitle file path (.srt)")
    
    # Common parameters
    parser.add_argument("-o", "--output", help="Output directory (default: ./final_mp3s)")
    parser.add_argument("-s", "--start", help="Start time (MM:SS or HH:MM:SS)")
    parser.add_argument("-e", "--end", help="End time (MM:SS or HH:MM:SS)")
    parser.add_argument("-l", "--lang", default="en", help="Subtitle language (default: en)")
    parser.add_argument("--source-dir", default="./source_files", help="Source files directory")
    parser.add_argument("--no-cleanup", action="store_true", help="Keep intermediate files")
    parser.add_argument("--enhance-stereo", action="store_true", help="Stereo enhancement")
    
    args = parser.parse_args()
    config = Config(args)
    
    try:
        if config.merge_mode:
            merge_mode(config)
        else:
            download_mode(config)
    except KeyboardInterrupt:
        print("\n❌ User interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()