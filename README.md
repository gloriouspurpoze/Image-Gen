# Image Generation for Services

A CLI tool that generates professional images for service cards (e.g., Fan Repair, Plumbing, AC Repair) using Google's Gemini API.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Get a Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Create an API key
3. Set it as an environment variable:

```bash
# Linux/macOS
export GEMINI_API_KEY="your-api-key-here"

# Windows (PowerShell)
$env:GEMINI_API_KEY = "your-api-key-here"

# Windows (CMD)
set GEMINI_API_KEY=your-api-key-here
```

Or pass it directly via `--api-key` flag.

## Usage

### Generate a single service image

```bash
python script1.py generate "Fan Repair Service"
```

With additional options:

```bash
python script1.py generate "AC Repair Service" --description "split AC servicing and gas refill" --style "isometric 3D" --aspect-ratio 1:1
```

### Generate multiple images (batch mode)

From a text file (one service per line):

```bash
python script1.py batch services_example.txt
```

From a JSON file (supports descriptions and styles per service):

```bash
python script1.py batch services_example.json
```

### Options

| Flag | Short | Description |
|---|---|---|
| `--api-key` | | Gemini API key (or set `GEMINI_API_KEY` env var) |
| `--output` | `-o` | Output directory (default: `./output`) |
| `--model` | `-m` | `imagen` (default, high quality) or `gemini` (multimodal) |
| `--aspect-ratio` | `-a` | `1:1` (default), `3:4`, `4:3`, `9:16`, `16:9` |
| `--count` | `-c` | Number of images per service (1-4, Imagen only) |
| `--description` | `-d` | Additional service description |
| `--style` | `-s` | Art style preference (e.g., `isometric 3D`, `watercolor`) |

### JSON file format

```json
[
  {
    "name": "Fan Repair Service",
    "description": "Ceiling fan and table fan repair",
    "style": "flat illustration"
  }
]
```

### Text file format

```
# Lines starting with # are ignored
Fan Repair Service
Plumbing Service
AC Repair Service
```

## Output

Generated images are saved to the `output/` folder with filenames like:

```
fan_repair_service_20260422_143052.png
```
