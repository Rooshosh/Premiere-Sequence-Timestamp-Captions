# Premiere Sequence Timestamp Captions

This script converts Adobe Premiere Pro sequence XML files into SRT caption files with timestamp information extracted from the video files.

## Usage

Run the script with your Premiere Pro sequence XML file as input:

```bash
python3 make_timestamps_srt.py <sequence.xml>
```

### Example

```bash
python3 make_timestamps_srt.py my_sequence.xml
```

## Output

The script will generate an SRT caption file in the same directory as your input XML file. The output file will be named `timestamps_<original_filename>.srt`.

For example, if your input file is `my_sequence.xml`, the output will be `timestamps_my_sequence.srt` in the same directory.

## What the script does

- Parses the Premiere Pro sequence XML file
- Extracts video clips from the first video track (V1)
- Extracts creation/modification timestamps from each video file using ExifTool
- Converts frame-based timeline positions to SRT timecode format
- Generates SRT captions showing the date and time for each clip

## Requirements

- Python 3
- ExifTool (for extracting metadata from video files)

## Notes

- The script only processes clips on the first video track (V1)
- Disabled clips are skipped
- If no timestamp metadata is found, clips will be marked as `[NO-DATE]`
- The script shows progress as it processes clips
