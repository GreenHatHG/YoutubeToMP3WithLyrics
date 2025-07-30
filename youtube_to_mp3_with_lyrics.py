#!/usr/bin/env python3

import os
import subprocess
import sys
import eyed3
import argparse
import re
import shutil
import time
from typing import List, Tuple, Optional, Dict

# ==============================================================================
#  Internal SRT to LRC Conversion Module
# ==============================================================================
def parse_time(time_str: str) -> float:
    """Parse time string in format HH:MM:SS.mmm or MM:SS.mmm"""
    if '.' not in time_str: time_str += '.000'
    parts = time_str.strip().split(':')
    if len(parts) == 3: h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    elif len(parts) == 2: h, m, s = 0, int(parts[0]), float(parts[1])
    else: raise ValueError(f"Unable to parse time format: {time_str}")
    return h * 3600 + m * 60 + s

def seconds_to_lrc_time(seconds: float) -> str:
    if seconds < 0: seconds = 0
    minutes = int(seconds // 60)
    secs = seconds % 60
    centiseconds = int((secs * 100) % 100)
    return f"[{minutes:02d}:{int(secs):02d}.{centiseconds:02d}]"

def parse_srt_file(srt_path: str) -> List[Tuple[float, float, str]]:
    """Parse SRT file and return list of (start_time, end_time, text) tuples"""
    subtitles = []
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if content.startswith('\ufeff'):
        content = content[1:]
    
    # SRT time pattern: 00:00:20,000 --> 00:00:24,400
    time_pattern = r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})'
    blocks = content.strip().split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
            
        # Skip sequence number (first line)
        time_line = lines[1]
        text_lines = lines[2:]
        
        time_match = re.search(time_pattern, time_line)
        if time_match:
            try:
                start_time_str = time_match.group(1).replace(',', '.')
                end_time_str = time_match.group(2).replace(',', '.')
                start_sec = parse_time(start_time_str)
                end_sec = parse_time(end_time_str)
                text_content = ' '.join(text_lines).strip()
                
                # Remove HTML tags and clean text
                text_content = re.sub(r'<[^>]+>', '', text_content).strip()
                
                if text_content:
                    subtitles.append((start_sec, end_sec, text_content))
            except ValueError as e:
                print(f"Warning: Skipping subtitle block: {lines[0]} - {e}")
    
    # Sort by start time and remove duplicates
    subtitles = sorted(subtitles, key=lambda x: x[0])
    
    # Simple deduplication for SRT (should be much cleaner than VTT)
    filtered_subtitles = []
    for current in subtitles:
        # Only add if it's not a duplicate of the previous subtitle
        if (not filtered_subtitles or 
            (current[2] != filtered_subtitles[-1][2] and 
             abs(current[0] - filtered_subtitles[-1][0]) > 0.1)):
            filtered_subtitles.append(current)
    
    return filtered_subtitles

def filter_subtitles(subs: List[Tuple[float, float, str]], start: float, end: float) -> List[Tuple[float, float, str]]:
    return [sub for sub in subs if sub[0] < end and sub[1] > start]

def convert_to_lrc_lines(subs: List[Tuple[float, float, str]], offset: float) -> List[str]:
    return [f"{seconds_to_lrc_time(s - offset)}{t}" for s, _, t in subs if s - offset >= 0]

def merge_audio_and_subtitle(audio_path: str, subtitle_path: str, output_dir: str, start_time: str = None, end_time: str = None, enhance_stereo: bool = False, source_dir: str = "./source_files", no_cleanup: bool = False):
    """Merge audio file and subtitle file into MP3 with embedded lyrics"""
    print("--- Starting Merge Mode ---")
    
    # Validate input files
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    if not os.path.exists(subtitle_path):
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")
    
    # Create source directory for intermediate files
    os.makedirs(source_dir, exist_ok=True)
    
    # Generate base names for source files
    audio_basename = os.path.splitext(os.path.basename(audio_path))[0]
    source_mp3_path = os.path.join(source_dir, f"{audio_basename}.mp3")
    source_lrc_path = os.path.join(source_dir, f"{audio_basename}.lrc")
    
    # Create output directory and generate final output path
    os.makedirs(output_dir, exist_ok=True)
    final_output_path = os.path.join(output_dir, f"{audio_basename}.mp3")
    
    # Create temporary directory for processing (only if needed)
    temp_dir = os.path.join(output_dir, ".temp_merge")
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # Step 1: Convert audio to MP3 if needed (check source_files first)
        if os.path.exists(source_mp3_path) and not enhance_stereo:
            print(f"✅ Found existing MP3 in source directory: {source_mp3_path}")
            temp_mp3_path = source_mp3_path
        else:
            temp_mp3_path = source_mp3_path  # Save directly to source directory
            audio_ext = os.path.splitext(audio_path)[1].lower()
            
            if audio_ext == '.mp3':
                print("✅ Input is already MP3, copying to source directory...")
                shutil.copy2(audio_path, temp_mp3_path)
                # Apply spatial stereo enhancement to MP3 if requested
                if enhance_stereo:
                    print("🔧 Applying spatial stereo enhancement to MP3...")
                    convert_to_spatial_stereo(temp_mp3_path)
            else:
                print(f"🔧 Converting {audio_ext} to MP3 and saving to source directory...")
                convert_to_mp3(audio_path, temp_mp3_path, enhance_stereo)
        
        # Step 2: Convert SRT to LRC (check source_files first)
        if os.path.exists(source_lrc_path):
            print(f"✅ Found existing LRC in source directory: {source_lrc_path}")
            temp_lrc_path = source_lrc_path
        else:
            temp_lrc_path = source_lrc_path  # Save directly to source directory
            print("🔧 Converting SRT to LRC and saving to source directory...")
            
            all_subs = parse_srt_file(subtitle_path)
            
            if start_time and end_time:
                # If time range is specified, filter and offset
                start_sec, end_sec = parse_time(start_time), parse_time(end_time)
                filtered_subs = filter_subtitles(all_subs, start_sec, end_sec)
                lrc_lines = convert_to_lrc_lines(filtered_subs, offset=start_sec)
                print(f"ℹ️  Applied time range filter: {start_time} to {end_time}")
            else:
                # If no time range specified, use all subtitles without offset
                lrc_lines = convert_to_lrc_lines(all_subs, offset=0)
                print("ℹ️  Using complete subtitles, no time filtering")
            
            with open(temp_lrc_path, 'w', encoding='utf-8') as f:
                f.write(f"[by:youtube_to_mp3_with_lyrics.py - merge mode]\n" + '\n'.join(lrc_lines))
            print(f"✅ SRT successfully converted to LRC: {temp_lrc_path}")
        
        # Step 3: Embed lyrics into MP3
        print("🔧 Embedding lyrics into MP3...")
        
        # Copy MP3 to final location
        shutil.copy2(temp_mp3_path, final_output_path)
        
        # Load and embed lyrics
        audiofile = eyed3.load(final_output_path)
        if audiofile is None:
            raise IOError("eyed3 cannot load the MP3 file.")
        if audiofile.tag is None:
            audiofile.initTag(version=eyed3.id3.ID3_V2_3)
        
        with open(temp_lrc_path, "r", encoding="utf-8") as f:
            lrc_text = f.read()
        
        audiofile.tag.lyrics.remove(u'')
        audiofile.tag.lyrics.set(lrc_text)
        audiofile.tag.save(version=eyed3.id3.ID3_V2_3, encoding='utf-8')
        
        print(f"✅ Successfully created MP3 with embedded lyrics: {final_output_path}")
        print(f"   Final file size: {os.path.getsize(final_output_path) / 1024:.2f} KB")
        
        # Clean up source files if not using no-cleanup
        if not no_cleanup:
            print("\n▶️  Cleaning up source files...")
            for f_path in [source_mp3_path, source_lrc_path]:
                if os.path.exists(f_path):
                    try: 
                        os.remove(f_path)
                        print(f"🗑️  Deleted: {f_path}")
                    except OSError as e: 
                        print(f"⚠️ Error cleaning up file: {e}")
        else:
            print(f"\n✅ Source files preserved in: {source_dir}")
        
    finally:
        # Clean up temporary directory (only if we used it)
        if os.path.exists(temp_dir) and temp_dir != source_dir:
            shutil.rmtree(temp_dir)
            print("🗑️  Cleaned up temporary files")
    
    print("--- 🎉 Merge completed successfully! ---")

# ==============================================================================
#  Main Execution Module (Refactored)
# ==============================================================================


def convert_to_spatial_stereo(audio_path: str):
    """Convert to spatial stereo"""
    print("🔧 Converting to spatial stereo...")
    temp_path = audio_path + ".temp.mp3"
    
    # Use spatial stereo filter
    filter_chain = "extrastereo=m=2.5,haas=level_in=1:level_out=1:side_gain=0.8,volume=0.7"
    convert_cmd = ["ffmpeg", "-i", audio_path, "-af", filter_chain, "-ac", "2", "-ar", "44100", "-b:a", "192k", "-y", temp_path]
    
    try:
        run_command(convert_cmd)
        os.replace(temp_path, audio_path)
        print("✅ Spatial stereo conversion completed! Both sides of headphones should now have distinct stereo effects")
        
        # Verify conversion result
        verify_cmd = ["ffprobe", "-v", "quiet", "-show_entries", "stream=channels", "-of", "csv=p=0", audio_path]
        verify_result = run_command(verify_cmd, quiet=True)
        final_channels = int(verify_result.strip()) if verify_result.strip().isdigit() else 0
        print(f"✅ Verification: Final channel count = {final_channels}")
        
    except Exception as e:
        print(f"❌ Conversion failed: {e}")
        # Clean up temporary files
        if os.path.exists(temp_path):
            os.remove(temp_path)

def convert_to_mp3(input_path: str, output_path: str, enhance_stereo: bool = False):
    """Convert any audio/video file to MP3 format"""
    print(f"🔧 Converting {input_path} to MP3...")
    
    # Check if input file exists
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_path)
    if output_dir:  # Only create directory if there's a directory path
        os.makedirs(output_dir, exist_ok=True)
    
    # Basic conversion command
    convert_cmd = ["ffmpeg", "-i", input_path, "-vn", "-acodec", "mp3", "-ab", "192k", "-ar", "44100", "-y", output_path]
    
    try:
        run_command(convert_cmd)
        print(f"✅ Successfully converted to: {output_path}")
        
        # Apply spatial stereo enhancement if requested
        if enhance_stereo:
            convert_to_spatial_stereo(output_path)
            
    except Exception as e:
        print(f"❌ Conversion failed: {e}")
        # Clean up output file if conversion failed
        if os.path.exists(output_path):
            os.remove(output_path)
        raise

def run_command(command: List[str], quiet: bool = False) -> str:
    if not quiet: print(f"\n▶️  Executing command: {' '.join(command)}")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        if quiet and "--list-subs" in command and (stdout.strip() or stderr.strip()):
             pass
        else:
            print(f"\n❌ Command execution failed, return code: {process.returncode}")
            print(f"   Command: {' '.join(command)}")
            print(f"   Error message: {stderr.strip()}")
            sys.exit(1)
    if not quiet:
        print("✅ Command executed successfully")
    return stdout + stderr

def get_video_metadata(url: str) -> Dict[str, str]:
    print("ℹ️  Getting video metadata...")
    title_raw = run_command(["yt-dlp", "--get-title", url], quiet=False).strip()
    title = re.sub(r'[\\/*?:"<>|]', '_', title_raw)
    video_id = run_command(["yt-dlp", "--get-id", url], quiet=False).strip()
    print(f"✅  Retrieved successfully: [ID: {video_id}, Title: {title}]")
    return {"id": video_id, "title": title}

def get_available_subtitles(url: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    print("ℹ️  Querying available subtitles...")
    max_retries = 3
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        output = run_command(["yt-dlp", "--list-subs", url], quiet=False)
        manual_subs, auto_subs = {}, {}
        lines = output.splitlines()
        parsing_manual, parsing_auto = False, False

        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check for section headers
            if "Available subtitles for" in line:
                parsing_manual, parsing_auto = True, False
                continue
            if "Available automatic captions for" in line:
                parsing_manual, parsing_auto = False, True
                continue
            
            # Skip header lines
            if line.lower().startswith(('language', 'id')) or line.startswith('---'):
                continue
            
            # Parse subtitle lines - format: "lang_code    Language Name    formats"
            # Use regex to match language code at start of line
            match = re.match(r'^([a-zA-Z0-9._-]+)\s+(.+?)\s+(?:vtt|srt|ttml)', line)
            if match:
                lang_code = match.group(1)
                lang_name = match.group(2).strip()
                
                if parsing_manual:
                    manual_subs[lang_code] = lang_name
                elif parsing_auto:
                    auto_subs[lang_code] = lang_name
        
        if manual_subs or auto_subs:
            print("✅ Subtitle query successful.")
            return manual_subs, auto_subs

        if attempt < max_retries - 1:
            print(f"⚠️  No subtitles found. This might be a temporary issue, retrying in {retry_delay} seconds ({attempt + 1}/{max_retries})...")
            time.sleep(retry_delay)
        else:
            print("⚠️  Still unable to get subtitle list after multiple attempts.")
    
    return {}, {}

def print_subtitle_lists(manual_subs: Dict[str, str], auto_subs: Dict[str, str]):
    def print_in_columns(title: str, subs: Dict[str, str]):
        if not subs:
            print(f"  {title} No available subtitles.")
            return
        print(f"  {title}")
        items = [f"{code}: {name}" for code, name in sorted(subs.items())]
        try:
            terminal_width = os.get_terminal_size().columns
        except OSError:
            terminal_width = 80
        max_len = max(len(item) for item in items) if items else 0
        col_width = max_len + 4
        num_cols = max(1, terminal_width // col_width)
        for i in range(0, len(items), num_cols):
            row_items = items[i:i+num_cols]
            line = "".join(item.ljust(col_width) for item in row_items)
            print(f"      {line}")
    print("--- Subtitle Availability Details ---")
    print_in_columns("📖 Available Manual Subtitles:", manual_subs)
    print("")
    print_in_columns("🤖 Available Auto Subtitles:", auto_subs)
    print("------------------------------------")

def parse_arguments():
    parser = argparse.ArgumentParser(description="Standalone YouTube audio and lyrics download tool with caching and directory management support.", epilog="Examples:\n  Download mode: python %(prog)s \"URL\" -s 0:00 -e 2:21 -o ./music\n  Merge mode: python %(prog)s --merge --audio audio.mp4 --subtitle subtitle.srt -o ./music", formatter_class=argparse.RawTextHelpFormatter)
    
    # Create mutually exclusive group for URL vs merge mode
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs='?', help="Complete URL of the target YouTube video.")
    group.add_argument("--merge", action="store_true", help="Merge mode: combine existing audio and subtitle files.")
    
    # Merge mode specific arguments
    parser.add_argument("--audio", help="Path to audio file (supports mp3, mp4, wav, etc.). Required in merge mode.")
    parser.add_argument("--subtitle", help="Path to subtitle file (.srt format). Required in merge mode.")
    
    # Common arguments
    parser.add_argument("-o", "--output", help="Output directory for final MP3 files (default: './final_mp3s').")
    parser.add_argument("-s", "--start", help="Trim start time (format: MM:SS or HH:MM:SS). If not provided, starts from beginning.")
    parser.add_argument("-e", "--end", help="Trim end time (format: MM:SS or HH:MM:SS). If not provided, goes to the end.")
    parser.add_argument("-l", "--lang", default="en", help="Subtitle language code (default is 'en').")
    parser.add_argument("--source-dir", default="./source_files", help="Directory for storing original downloaded files and LRC.")
    parser.add_argument("--no-cleanup", action="store_true", help="Keep all intermediate files in source directory.")
    parser.add_argument("--enhance-stereo", action="store_true", help="Apply spatial stereo enhancement to mono or pseudo-stereo audio.")
    return parser.parse_args()

def main():
    args = parse_arguments()
    print("--- Process Started ---")

    # Handle merge mode
    if args.merge:
        # Validate required arguments for merge mode
        if not args.audio:
            sys.exit("❌ Error: --audio is required in merge mode")
        if not args.subtitle:
            sys.exit("❌ Error: --subtitle is required in merge mode")
        
        # Determine output directory for merge mode
        merge_output_dir = args.output if args.output else "./final_mp3s"
        
        try:
            merge_audio_and_subtitle(
                audio_path=args.audio,
                subtitle_path=args.subtitle,
                output_dir=merge_output_dir,
                start_time=args.start,
                end_time=args.end,
                enhance_stereo=args.enhance_stereo,
                source_dir=args.source_dir,
                no_cleanup=args.no_cleanup
            )
            return
        except Exception as e:
            sys.exit(f"❌ Merge failed: {e}")

    # Original YouTube download mode
    if not args.url:
        sys.exit("❌ Error: URL is required when not in merge mode")

    try:
        metadata = get_video_metadata(args.url)
        final_base_name = f"{metadata['title']} [{metadata['id']}]"
        source_base_name = metadata['id']
        
        # Determine output directory: use --output if provided, otherwise default to ./final_mp3s
        output_dir = args.output if args.output else "./final_mp3s"
        
        os.makedirs(args.source_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        final_mp3_path = os.path.join(output_dir, f"{final_base_name}.mp3")
        source_mp3_path = os.path.join(args.source_dir, f"{source_base_name}.mp3")
        source_srt_path = os.path.join(args.source_dir, f"{source_base_name}.{args.lang}.srt")
        source_lrc_path = os.path.join(args.source_dir, f"{source_base_name}.lrc")
    except Exception as e:
        sys.exit(f"❌ Unable to get video metadata: {e}")

    if os.path.exists(final_mp3_path):
        print(f"✅ Task completed. Final file already exists at: {final_mp3_path}")
        sys.exit(0)

    manual_subs, auto_subs = get_available_subtitles(args.url)
    
    use_auto_sub = False
    if args.lang in manual_subs:
        print(f"✅ Found requested manual subtitles: '{args.lang}' ({manual_subs[args.lang]})")
    elif args.lang in auto_subs:
        print(f"\n⚠️  Warning: Manual subtitles '{args.lang}' not found. Will use auto-generated subtitles instead.")
        print_subtitle_lists(manual_subs, auto_subs)
        use_auto_sub = True
    else:
        print(f"\n❌ Error: Cannot find requested subtitle language '{args.lang}'.")
        if not manual_subs and not auto_subs:
            print("   Reason: Unable to get any available subtitle list from YouTube. This might be a temporary network issue or video restriction. Please try again later.")
        else:
             print_subtitle_lists(manual_subs, auto_subs)
        sys.exit(1)

    if not os.path.exists(source_mp3_path) or not os.path.exists(source_srt_path):
        print("\nℹ️  Source files don't exist, starting download...")
        output_template = os.path.join(args.source_dir, f"{source_base_name}.%(ext)s")
        dl_command = ["yt-dlp", "-x", "--audio-format", "mp3"]
        if use_auto_sub:
            dl_command.extend(["--write-auto-sub", "--sub-lang", args.lang, "--sub-format", "srt"])
        else:
            dl_command.extend(["--write-sub", "--sub-lang", args.lang, "--sub-format", "srt"])
        
        # Only add trimming parameters when start and end times are provided
        if args.start and args.end:
            dl_command.extend(["--download-sections", f"*{args.start}-{args.end}"])
            print(f"ℹ️  Will trim segment: {args.start} to {args.end}")
        else:
            print("ℹ️  No time range specified, will download complete video")
        
        dl_command.extend(["-o", output_template, args.url])
        run_command(dl_command)
        
        # Apply spatial stereo enhancement if user requested
        if os.path.exists(source_mp3_path):
            if args.enhance_stereo:
                print("\nℹ️  User requested spatial stereo enhancement...")
                convert_to_spatial_stereo(source_mp3_path)
            else:
                print("\nℹ️  Spatial stereo enhancement not requested, skipping.")
    else:
        print("\n✅ Detected existing source MP3 and SRT files, skipping download.")
        # Apply spatial stereo enhancement to cached files if user requested
        if os.path.exists(source_mp3_path):
            if args.enhance_stereo:
                print("\nℹ️  User requested spatial stereo enhancement for cached files...")
                convert_to_spatial_stereo(source_mp3_path)
            else:
                print("\nℹ️  Spatial stereo enhancement not requested, skipping.")

    if not os.path.exists(source_srt_path):
        sys.exit(f"❌ Error: Subtitle file {source_srt_path} failed to download. Please check language code and network connection.")
    if not os.path.exists(source_lrc_path):
        print("\n▶️  Converting SRT to LRC...")
        try:
            all_subs = parse_srt_file(source_srt_path)
            
            if args.start and args.end:
                # If time range is specified, filter and offset
                start_sec, end_sec = parse_time(args.start), parse_time(args.end)
                filtered_subs = filter_subtitles(all_subs, start_sec, end_sec)
                lrc_lines = convert_to_lrc_lines(filtered_subs, offset=start_sec)
                print(f"ℹ️  Filtered subtitle time range: {args.start} to {args.end}")
            else:
                # If no time range specified, use all subtitles without offset
                lrc_lines = convert_to_lrc_lines(all_subs, offset=0)
                print("ℹ️  Using complete subtitles, no time offset")
            
            with open(source_lrc_path, 'w', encoding='utf-8') as f: 
                f.write(f"[by:youtube_to_mp3_with_lyrics.py]\n" + '\n'.join(lrc_lines))
            print(f"✅ SRT successfully converted to {source_lrc_path}")
        except Exception as e: 
            sys.exit(f"❌ Error occurred during SRT to LRC conversion: {e}")
    else:
        print("✅ Detected existing LRC file, skipping conversion.")
    print("\n▶️  Starting to embed lyrics and generate final file...")
    try:
        shutil.copy2(source_mp3_path, final_mp3_path)
        audiofile = eyed3.load(final_mp3_path)
        if audiofile is None: raise IOError("eyed3 cannot load the final MP3 file.")
        if audiofile.tag is None: audiofile.initTag(version=eyed3.id3.ID3_V2_3)
        with open(source_lrc_path, "r", encoding="utf-8") as f: lrc_text = f.read()
        audiofile.tag.lyrics.remove(u'')
        audiofile.tag.lyrics.set(lrc_text)
        audiofile.tag.save(version=eyed3.id3.ID3_V2_3, encoding='utf-8')
        print(f"✅ Successfully embedded lyrics and saved to: {final_mp3_path}")
        print(f"   Final file size: {os.path.getsize(final_mp3_path) / 1024:.2f} KB")
    except Exception as e: sys.exit(f"❌ Error occurred while embedding lyrics: {e}")
    if not args.no_cleanup:
        print("\n▶️  Cleaning up source files...")
        for f_path in [source_mp3_path, source_srt_path, source_lrc_path]:
            if os.path.exists(f_path):
                try: os.remove(f_path); print(f"🗑️  Deleted: {f_path}")
                except OSError as e: print(f"⚠️ Error cleaning up file: {e}")
    print("\n--- 🎉 All processes completed successfully! ---")

if __name__ == "__main__":
    main()