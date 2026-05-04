"""
Automated image generation & upload for ProFixer service listings.

Flow:
  1. Fetch services from ProFixer API (by category)
  2. Filter services that still have the default placeholder image
  3. Generate a product-style image via Gemini API
  4. Upload the image to Cloudinary via ProFixer upload endpoint
  5. Update the service record with the new image URL
"""

import os
import re
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ClientError

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
BEARER_TOKEN = os.getenv("PROFIXER_BEARER_TOKEN", "")
API_BASE = os.getenv("PROFIXER_API_BASE", "https://api.profixer.in/api")

DEFAULT_PLACEHOLDER = (
    "https://res.cloudinary.com/ddobj9gmr/image/upload/"
    "v1761665533/IMG-20251028-WA0054_dkzkij.jpg"
)

# GEMINI_IMAGE_MODEL = "gemini-2.0-flash-exp"
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image-preview"
OUTPUT_DIR = Path(__file__).parent / "output"

PROMPT_TEMPLATE = (
    'A single product or object that best represents the "{service_name}" home service, '
    "centered on a smooth dark gray-to-charcoal gradient background. "
    "Soft diffused studio lighting from above and sides, subtle shadow beneath. "
    "Photorealistic, clean, white/silver tones on the product, no text anywhere, "
    "no watermarks, no logos, no people, no hands. "
    "Sharp focus, high detail, isolated object, generous padding around the subject. "
    "Professional product photography style matching an electrical/plumbing services catalog."
)

SKIP_CATEGORIES = {"electrician", "ac"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def sanitize_filename(name: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[\s]+", "_", clean).strip("_")


def profixer_headers():
    return {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Step 1: Fetch services from ProFixer
# ---------------------------------------------------------------------------


def fetch_services(category: str) -> list[dict]:
    url = f"{API_BASE}/platform-services/public?category={category}"
    log(f"Fetching services: {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    services = data if isinstance(data, list) else data.get("data", data.get("services", []))
    log(f"  Found {len(services)} services in '{category}'")
    return services


# ---------------------------------------------------------------------------
# Step 2: Filter — only services with the default placeholder image
# ---------------------------------------------------------------------------


def needs_image(service: dict) -> bool:
    img = service.get("image", "")
    if not img:
        return True
    return img.strip() == DEFAULT_PLACEHOLDER.strip()


# ---------------------------------------------------------------------------
# Step 3: Generate image via Gemini
# ---------------------------------------------------------------------------


def get_gemini_client() -> genai.Client:
    if not GEMINI_API_KEY:
        log("No GEMINI_API_KEY found in .env", "ERROR")
        sys.exit(1)
    return genai.Client(api_key=GEMINI_API_KEY)


def generate_image(
    client: genai.Client,
    service_name: str,
    max_retries: int = 5,
) -> bytes | None:
    prompt = PROMPT_TEMPLATE.format(service_name=service_name)
    log(f"  Generating image for: {service_name}")

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )

            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        log(f"  Image generated successfully ({len(part.inline_data.data)} bytes)")
                        return part.inline_data.data

            log("  No image data in response", "WARN")
            return None

        except ClientError as e:
            if e.code == 429:
                retry_match = re.search(r"retry in ([\d.]+)s", str(e), re.IGNORECASE)
                wait = float(retry_match.group(1)) + 5 if retry_match else 30 * attempt
                wait = min(wait, 120)

                if attempt < max_retries:
                    log(f"  Rate limited. Waiting {wait:.0f}s (attempt {attempt}/{max_retries})...", "WARN")
                    time.sleep(wait)
                else:
                    log("  Rate limit exhausted after all retries.", "ERROR")
                    log("  Your API key may need billing enabled for image generation.", "ERROR")
                    log("  Visit: https://aistudio.google.com/apikey", "ERROR")
                    return None
            else:
                log(f"  Gemini API error: {e}", "ERROR")
                return None
        except Exception as e:
            log(f"  Unexpected error: {e}", "ERROR")
            return None

    return None


def save_image_locally(image_data: bytes, service_name: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{sanitize_filename(service_name)}_{ts}.png"
    filepath = OUTPUT_DIR / filename
    with open(filepath, "wb") as f:
        f.write(image_data)
    log(f"  Saved locally: {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# Step 4: Upload image to Cloudinary via ProFixer API
# ---------------------------------------------------------------------------


def upload_image(image_path: Path) -> str | None:
    url = f"{API_BASE}/upload/image"
    log(f"  Uploading to ProFixer: {image_path.name}")

    with open(image_path, "rb") as f:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {BEARER_TOKEN}"},
            files={"image": (image_path.name, f, "image/png")},
            timeout=60,
        )

    if resp.status_code != 200:
        log(f"  Upload failed ({resp.status_code}): {resp.text}", "ERROR")
        return None

    data = resp.json()
    if data.get("success"):
        cloud_url = data["data"]["url"]
        log(f"  Uploaded: {cloud_url}")
        return cloud_url

    log(f"  Upload response not successful: {data}", "ERROR")
    return None


# ---------------------------------------------------------------------------
# Step 5: Update service record with new image
# ---------------------------------------------------------------------------


def update_service_image(service_id: str, image_url: str, service_data: dict) -> bool:
    url = f"{API_BASE}/platform-services/{service_id}"
    log(f"  Updating service {service_id} with new image...")

    payload = {
        "image": image_url,
        "images": [image_url],
    }

    resp = requests.put(
        url,
        headers=profixer_headers(),
        json=payload,
        timeout=30,
    )

    if resp.status_code == 200:
        log(f"  Service updated successfully!")
        return True

    log(f"  Update failed ({resp.status_code}): {resp.text}", "ERROR")
    return False


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(categories: list[str], dry_run: bool = False, delay: float = 10.0):
    log("=" * 60)
    log("ProFixer Image Generation Pipeline")
    log("=" * 60)

    if dry_run:
        log("DRY RUN MODE — no uploads or updates will be made", "WARN")

    client = get_gemini_client()

    stats = {"total": 0, "skipped": 0, "generated": 0, "uploaded": 0, "failed": 0}

    for category in categories:
        log(f"\n{'─' * 40}")
        log(f"Category: {category}")
        log(f"{'─' * 40}")

        if category.lower() in SKIP_CATEGORIES:
            log(f"  Skipping category '{category}' (in skip list)")
            continue

        try:
            services = fetch_services(category)
        except Exception as e:
            log(f"  Failed to fetch services: {e}", "ERROR")
            continue

        to_process = [s for s in services if needs_image(s)]
        already_done = len(services) - len(to_process)

        log(f"  {already_done} already have images, {len(to_process)} need generation")
        stats["total"] += len(services)
        stats["skipped"] += already_done

        for idx, service in enumerate(to_process, 1):
            svc_name = service.get("display_name") or service.get("name", "Unknown")
            svc_id = service.get("_id", "")

            log(f"\n[{idx}/{len(to_process)}] {svc_name} (id: {svc_id})")

            # Generate
            image_data = generate_image(client, svc_name)
            if not image_data:
                stats["failed"] += 1
                continue

            # Save locally
            local_path = save_image_locally(image_data, svc_name)
            stats["generated"] += 1

            if dry_run:
                log("  DRY RUN — skipping upload & update")
                continue

            # Upload
            cloud_url = upload_image(local_path)
            if not cloud_url:
                stats["failed"] += 1
                continue

            # Update service
            success = update_service_image(svc_id, cloud_url, service)
            if success:
                stats["uploaded"] += 1
            else:
                stats["failed"] += 1

            # Delay between services to avoid rate limits
            if idx < len(to_process):
                log(f"  Waiting {delay:.0f}s before next service...")
                time.sleep(delay)

    # Summary
    log(f"\n{'=' * 60}")
    log("PIPELINE COMPLETE")
    log(f"  Total services:  {stats['total']}")
    log(f"  Already had img: {stats['skipped']}")
    log(f"  Generated:       {stats['generated']}")
    log(f"  Uploaded+Updated:{stats['uploaded']}")
    log(f"  Failed:          {stats['failed']}")
    log(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# CLI for single image generation (testing)
# ---------------------------------------------------------------------------


def generate_single(service_name: str):
    """Generate a single image locally for testing (no upload)."""
    client = get_gemini_client()
    prompt = PROMPT_TEMPLATE.format(service_name=service_name)
    log(f"Prompt: {prompt}\n")

    image_data = generate_image(client, service_name)
    if image_data:
        save_image_locally(image_data, service_name)
        log("Done!")
    else:
        log("Failed to generate image.", "ERROR")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generate & upload service images for ProFixer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test: generate one image locally (no upload)
  python script1.py test "Tap Repair & Installation"

  # Dry run: see what would be processed (no upload/update)
  python script1.py run --category plumber --dry-run

  # Full run: generate, upload, and update plumber services
  python script1.py run --category plumber

  # Multiple categories
  python script1.py run --category plumber --category carpenter
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # 'test' — generate single image locally
    test_parser = subparsers.add_parser("test", help="Generate a single image locally (no upload)")
    test_parser.add_argument("service", help="Service name, e.g. 'Fan Repair Service'")

    # 'run' — full pipeline
    run_parser = subparsers.add_parser("run", help="Run the full pipeline for a category")
    run_parser.add_argument(
        "--category", "-c",
        action="append",
        required=True,
        help="Category to process (repeat for multiple). 'electrician' and 'ac' are auto-skipped.",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate images locally but skip upload & service update",
    )
    run_parser.add_argument(
        "--delay",
        type=float,
        default=10.0,
        help="Seconds to wait between services (default: 10, helps with rate limits)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "test":
        generate_single(args.service)
    elif args.command == "run":
        run_pipeline(args.category, dry_run=args.dry_run, delay=args.delay)


if __name__ == "__main__":
    main()
