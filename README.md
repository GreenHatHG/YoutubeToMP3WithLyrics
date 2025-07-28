# YouTube to MP3 with Lyrics

A powerful Python tool that downloads YouTube videos, extracts audio segments, and embeds synchronized lyrics into MP3 files. This tool automatically downloads subtitles, converts them to LRC format, and embeds them directly into the MP3 metadata.

![](images/2025-07-28_152226.png)

## Features

- 🎵 **Audio Extraction**: Download and extract high-quality MP3 audio from YouTube videos
- 📝 **Subtitle Processing**: Automatically download and convert VTT subtitles to LRC format
- ⏱️ **Time-based Segmentation**: Extract specific time segments from videos
- 🎤 **Lyrics Embedding**: Embed synchronized lyrics directly into MP3 metadata
- 🗂️ **Smart Caching**: Avoid re-downloading existing files with intelligent caching
- 🧹 **Clean Workflow**: Automatic cleanup of intermediate files (optional)
- 🌍 **Multi-language Support**: Support for multiple subtitle languages

## Prerequisites

- Python 3.6 or higher
- `yt-dlp` (YouTube downloader)
- `ffmpeg` (for audio processing)

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd YoutubeToMP3WithLyrics
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install system dependencies:**
   - **Ubuntu/Debian:**
     ```bash
     sudo apt update
     sudo apt install ffmpeg
     ```
   - **macOS:**
     ```bash
     brew install ffmpeg
     ```
   - **Windows:**
     Download ffmpeg from [official website](https://ffmpeg.org/download.html) and add to PATH

## Usage

### Basic Usage

```bash
python youtube_to_mp3_with_lyrics.py "YOUTUBE_URL" -s START_TIME -e END_TIME
```

### Parameters

- `url`: YouTube video URL (required)
- `-s, --start`: Start time in MM:SS or HH:MM:SS format (required)
- `-e, --end`: End time in MM:SS or HH:MM:SS format (required)
- `-l, --lang`: Subtitle language code (default: 'en')
- `--source-dir`: Directory for source files (default: './source_files')
- `--output-dir`: Directory for final MP3 files (default: './final_mp3s')
- `--no-cleanup`: Keep all intermediate files

### Examples

1. **Extract a 2-minute segment with English subtitles:**
   ```bash
   python youtube_to_mp3_with_lyrics.py "https://www.youtube.com/watch?v=VIDEO_ID" -s 1:30 -e 3:30
   ```

2. **Extract with Spanish subtitles:**
   ```bash
   python youtube_to_mp3_with_lyrics.py "https://www.youtube.com/watch?v=VIDEO_ID" -s 0:00 -e 5:00 -l es
   ```

3. **Custom directories and keep intermediate files:**
   ```bash
   python youtube_to_mp3_with_lyrics.py "https://www.youtube.com/watch?v=VIDEO_ID" -s 2:15 -e 4:45 --source-dir ./downloads --output-dir ./music --no-cleanup
   ```

## How It Works

1. **Metadata Extraction**: Retrieves video title and ID from YouTube
2. **Content Download**: Downloads audio and subtitle files using yt-dlp
3. **Subtitle Processing**: Converts VTT subtitles to LRC format with proper timing
4. **Audio Segmentation**: Extracts the specified time segment from the audio
5. **Lyrics Embedding**: Embeds synchronized lyrics into MP3 metadata using eyeD3
6. **File Organization**: Saves the final MP3 with embedded lyrics to the output directory
7. **Cleanup**: Optionally removes intermediate files

## Dependencies

- **yt-dlp**: YouTube video/audio downloader
- **eyeD3**: MP3 metadata manipulation
- **Standard libraries**: os, subprocess, sys, argparse, re, shutil, typing

## Supported Subtitle Languages

The tool supports any language code that YouTube provides subtitles for. Common codes include:
- `en` - English
- `es` - Spanish
- `fr` - French
- `de` - German
- `ja` - Japanese
- `ko` - Korean
- `zh` - Chinese

## Error Handling

The tool includes comprehensive error handling for:
- Invalid YouTube URLs
- Missing subtitles
- Network connectivity issues
- File permission problems
- Invalid time formats
- Audio processing errors

## Troubleshooting

1. **"Command not found" errors**: Ensure yt-dlp and ffmpeg are properly installed
2. **Permission errors**: Check write permissions for output directories
3. **Subtitle not available**: Try different language codes or check if subtitles exist
4. **Invalid time format**: Use MM:SS or HH:MM:SS format (e.g., 1:30 or 0:01:30)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is for educational and personal use. Please respect YouTube's Terms of Service and copyright laws when using this tool.

## Disclaimer

This tool is intended for personal use and educational purposes. Users are responsible for ensuring they have the right to download and use the content they process with this tool.
