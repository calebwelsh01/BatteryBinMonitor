#!/usr/bin/env python3
"""
BatteryBin - all-in-one (Raspberry Pi 5, no Arduino)
-----------------------------------------------------
Replaces python_listener.py + identify_battery.py + upload_battery_data.py
and the Arduino Mega. Everything runs on the Pi:

  Button press (GPIO)  ->  capture photo(s) from 1-2 webcams
                       ->  OpenAI vision identifies the battery
                       ->  result XML written next to the photo
                       ->  primary photo + result uploaded to Supabase
                       ->  solenoid pulsed (only if a battery was detected)

  Status and results are printed to stdout (visible with
  `journalctl -u battery-listener -f` when run as a service).

  While idle, any photo/XML pairs that failed to upload earlier are retried
  every --sync-interval minutes (what upload_battery_data.py used to do).

Wiring (BCM numbering - change the constants below to suit):
  Button    : GPIO17 (pin 11) -> button -> GND   (internal pull-up used)
  Solenoid  : GPIO27 (pin 13) -> MOSFET gate / relay input. NEVER drive the
              solenoid straight off a GPIO pin; use a logic-level MOSFET
              with a flyback diode across the coil, and a separate supply.

Setup:
    sudo apt install python3-lgpio
    pip install opencv-python openai supabase gpiozero lgpio

Environment variables:
    OPENAI_API_KEY, SUPABASE_URL, SUPABASE_KEY (service_role key)

Usage:
    python batterybin.py                      # normal mode: wait for button
    python batterybin.py --test               # run one cycle now, no button
    python batterybin.py --sync-only          # just upload any backlog, exit
    python batterybin.py --camera2 -1         # single camera only
    python batterybin.py --no-upload          # local-only (no Supabase)
"""

import argparse
import base64
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from xml.dom import minidom

import cv2
from gpiozero import Button, OutputDevice
from openai import OpenAI

# ---------------------------------------------------------------------------
# Hardware config (BCM GPIO numbers)
# ---------------------------------------------------------------------------
BUTTON_PIN = 17
SOLENOID_PIN = 27
SOLENOID_PULSE_S = 0.5        # how long the solenoid stays energised
SOLENOID_ACTIVE_HIGH = True   # set False if your relay board is active-low

# ---------------------------------------------------------------------------
# Supabase / file config
# ---------------------------------------------------------------------------
BUCKET_NAME = "battery-photos"
TABLE_NAME = "battery_readings"
STATE_FILENAME = ".uploaded_state.json"
OPENAI_MODEL = "gpt-4o-mini"  # "gpt-4o" for higher accuracy
OPENAI_TIMEOUT_S = 30


# ===========================================================================
# Camera
# ===========================================================================
def capture_webcam_photo(
    camera_index: int,
    save_path: Path,
    width: int = None,
    height: int = None,
    autofocus: bool = None,
    focus: int = None,
    brightness: int = None,
) -> Path:
    """Capture one frame from a USB webcam and save it.

    Uses V4L2 + MJPG so higher resolutions are available (YUYV is usually
    capped around 480p by USB bandwidth). FOURCC must be set before the
    resolution. With no width/height, an oversized request makes the driver
    clamp to the camera's maximum.
    """
    cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {camera_index}.")

    try:
        if not cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")):
            print("WARNING: camera didn't accept MJPG - resolution may be capped low.")

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width or 9999)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height or 9999)

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"Camera {camera_index} resolution: {w}x{h}")

        if autofocus is not None:
            if not cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if autofocus else 0):
                print("WARNING: camera didn't accept the autofocus setting.")
            if autofocus is False and focus is not None:
                if not cap.set(cv2.CAP_PROP_FOCUS, focus):
                    print("WARNING: camera didn't accept the manual focus value.")

        if brightness is not None:
            if not cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness):
                print("WARNING: camera didn't accept the brightness value.")

        # Let exposure/focus settle for a few frames.
        frame = None
        for _ in range(10):
            ret, frame = cap.read()
            if not ret:
                raise RuntimeError(f"Failed to read frame from camera {camera_index}.")
    finally:
        cap.release()

    cv2.imwrite(str(save_path), frame)
    print(f"Photo saved: {save_path}")
    return save_path


def capture_images(args, bin_dir: Path) -> list:
    """Capture from the primary camera and (optionally) the second camera."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    two_cams = args.camera2 is not None and args.camera2 >= 0

    cam_kwargs = dict(
        width=args.cap_width,
        height=args.cap_height,
        autofocus=None if args.autofocus is None else args.autofocus == "on",
        focus=args.focus,
        brightness=args.brightness,
    )

    paths = []
    name1 = f"battery_photo_cam1_{timestamp}.jpg" if two_cams else f"battery_photo_{timestamp}.jpg"
    paths.append(capture_webcam_photo(args.camera, bin_dir / name1, **cam_kwargs))

    if two_cams:
        name2 = f"battery_photo_cam2_{timestamp}.jpg"
        paths.append(capture_webcam_photo(args.camera2, bin_dir / name2, **cam_kwargs))

    return paths


# ===========================================================================
# OpenAI identification
# ===========================================================================
def identify_battery(image_paths: list, api_key: str) -> dict:
    """Send all images in one request; return is_battery, battery_type,
    reasoning and guess."""
    if len(image_paths) > 1:
        intro = (
            "You are looking at multiple photos, possibly of the SAME battery "
            "taken from different angles/cameras. Use all images together to "
            "determine whether they show a battery, and if so, what type.\n\n"
        )
        reasoning_hint = (
            "brief explanation, noting details from each image if relevant "
            "(e.g. a label only visible from one angle)"
        )
    else:
        intro = "Is this a battery? If so, what type?\n\n"
        reasoning_hint = "brief explanation"

    prompt = (
        intro
        + "Respond with ONLY a JSON object (no markdown fences, no extra text) "
        "in exactly this format:\n"
        "{\n"
        '  "is_battery": true or false,\n'
        '  "battery_type": "the battery type if is_battery is true (e.g. AA, '
        '9V, CR2032), or \\"unknown\\" if unclear, or \\"none\\" if not a '
        'battery",\n'
        f'  "reasoning": "{reasoning_hint}",\n'
        '  "guess": "your best guess at the SPECIFIC battery type/format, '
        "even if not confident enough to put in battery_type - a short "
        'code/label only, no sentences (e.g. \\"18650\\", \\"21700\\", '
        '\\"lead-acid\\", \\"CR2032\\", \\"AAA\\"), or \\"unknown\\" if you '
        'really cannot narrow it down"\n'
        "}"
    )

    content = [{"type": "text", "text": prompt}]
    for path in image_paths:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    client = OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_S)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=450,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Model did not return valid JSON: {e}\nRaw response: {raw}")

    is_battery = bool(parsed.get("is_battery", False))
    result = {
        "is_battery": is_battery,
        "battery_type": str(parsed.get("battery_type", "unknown")).strip() if is_battery else "none",
        "reasoning": str(parsed.get("reasoning", "")).strip(),
        "guess": str(parsed.get("guess", "")).strip() or "unknown",
    }
    return result


# ===========================================================================
# XML
# ===========================================================================
def write_result_xml(image_paths: list, result: dict, xml_path: Path) -> Path:
    root = ET.Element("BatteryIdentification")
    for path in image_paths:
        ET.SubElement(root, "PhotoFilename").text = Path(path).name
    ET.SubElement(root, "IsBattery").text = str(result["is_battery"]).lower()
    ET.SubElement(root, "BatteryType").text = result["battery_type"]
    ET.SubElement(root, "Reasoning").text = result["reasoning"]
    ET.SubElement(root, "Guess", {"type": "prediction"}).text = result["guess"]
    ET.SubElement(root, "Timestamp").text = datetime.now().isoformat(timespec="seconds")

    pretty = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(indent="  ")
    xml_path.write_text(pretty, encoding="utf-8")
    print(f"Result written to: {xml_path}")
    return xml_path


def parse_reading_xml(xml_path: Path) -> dict:
    root = ET.parse(xml_path).getroot()

    def text_of(tag, default=""):
        el = root.find(tag)  # first <PhotoFilename> = primary camera
        return el.text if el is not None and el.text is not None else default

    return {
        "photo_filename": text_of("PhotoFilename"),
        "is_battery": text_of("IsBattery", "false").strip().lower() == "true",
        "battery_type": text_of("BatteryType", "unknown"),
        "reasoning": text_of("Reasoning", ""),
        "captured_at": text_of("Timestamp"),
    }


# ===========================================================================
# Supabase upload + backlog sync
# ===========================================================================
def make_supabase_client(args):
    if args.no_upload:
        print("Uploads disabled (--no-upload).")
        return None

    url = args.supabase_url or os.environ.get("SUPABASE_URL")
    key = args.supabase_key or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("WARNING: SUPABASE_URL / SUPABASE_KEY not set - running without uploads.",
              file=sys.stderr)
        return None

    from supabase import create_client
    return create_client(url, key)


def load_state(bin_dir: Path) -> set:
    path = bin_dir / STATE_FILENAME
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            print("WARNING: upload state file unreadable - starting fresh.")
    return set()


def save_state(bin_dir: Path, uploaded: set) -> None:
    (bin_dir / STATE_FILENAME).write_text(json.dumps(sorted(uploaded), indent=2), encoding="utf-8")


def mark_uploaded(bin_dir: Path, image_name: str) -> None:
    uploaded = load_state(bin_dir)
    uploaded.add(image_name)
    save_state(bin_dir, uploaded)


def upload_pair(client, image_path: Path, xml_path: Path) -> None:
    """Upload the primary photo to Storage and upsert its row.
    photo_filename is unique, so re-uploads never duplicate rows."""
    reading = parse_reading_xml(xml_path)
    storage_path = image_path.name

    client.storage.from_(BUCKET_NAME).upload(
        storage_path,
        image_path.read_bytes(),
        file_options={"content-type": "image/jpeg", "upsert": "true"},
    )
    public_url = client.storage.from_(BUCKET_NAME).get_public_url(storage_path)

    client.table(TABLE_NAME).upsert(
        {
            "photo_filename": reading["photo_filename"] or storage_path,
            "photo_url": public_url,
            "is_battery": reading["is_battery"],
            "battery_type": reading["battery_type"],
            "reasoning": reading["reasoning"],
            "captured_at": reading["captured_at"] or None,
        },
        on_conflict="photo_filename",
    ).execute()
    print(f"Uploaded: {storage_path} -> {reading['battery_type']}")


def find_pairs(bin_dir: Path):
    """Yield (image_path, xml_path) for every XML that has a matching image.
    XMLs are named after the primary photo, so cam2 photos are never uploaded."""
    for xml_path in sorted(bin_dir.glob("*.xml")):
        for ext in (".jpg", ".jpeg", ".png"):
            candidate = xml_path.with_suffix(ext)
            if candidate.exists():
                yield candidate, xml_path
                break


def sync_backlog(client, bin_dir: Path) -> None:
    uploaded = load_state(bin_dir)
    new = 0
    for image_path, xml_path in find_pairs(bin_dir):
        if image_path.name in uploaded:
            continue
        try:
            upload_pair(client, image_path, xml_path)
            uploaded.add(image_path.name)
            new += 1
        except Exception as e:
            print(f"ERROR uploading {image_path.name}: {e}", file=sys.stderr)
    if new:
        save_state(bin_dir, uploaded)
        print(f"Backlog sync: {new} file(s) uploaded.")


# ===========================================================================
# One full button-press cycle
# ===========================================================================
def pulse_solenoid(solenoid: OutputDevice) -> None:
    solenoid.on()
    time.sleep(SOLENOID_PULSE_S)
    solenoid.off()


def run_cycle(args, solenoid: OutputDevice, supa, bin_dir: Path, api_key: str) -> None:
    try:
        print("Capturing...")
        image_paths = capture_images(args, bin_dir)

        print("Identifying...")
        result = identify_battery(image_paths, api_key)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return

    print("\n=== Battery Identification ===")
    print(f"Is battery: {result['is_battery']}")
    print(f"Battery type: {result['battery_type']}")
    print(f"Reasoning: {result['reasoning']}")
    print(f"Guess (prediction): {result['guess']}")

    primary = Path(image_paths[0])
    xml_path = write_result_xml(image_paths, result, primary.with_suffix(".xml"))

    # Upload before firing the solenoid; a failure here doesn't stop the bin -
    # the pair stays in the backlog and is retried while idle.
    if supa:
        print("Uploading...")
        try:
            upload_pair(supa, primary, xml_path)
            mark_uploaded(bin_dir, primary.name)
        except Exception as e:
            print(f"Upload failed (will retry later): {e}", file=sys.stderr)

    if result["is_battery"]:
        pulse_solenoid(solenoid)
        print("Battery detected - solenoid pulsed")
    else:
        print("No battery detected - solenoid not triggered")


# ===========================================================================
# Main
# ===========================================================================
def parse_args():
    p = argparse.ArgumentParser(description="BatteryBin all-in-one controller for Raspberry Pi 5.")
    p.add_argument("--bin-dir", default=str(Path(__file__).resolve().parent),
                   help="Folder for photos, XML and upload state (default: this script's folder)")
    p.add_argument("--camera", type=int, default=0, help="Primary webcam index (default: 0)")
    p.add_argument("--camera2", type=int, default=2, help="Second webcam index, or -1 to disable (default: 2)")
    p.add_argument("--resolution", default=None, help="Capture resolution WIDTHxHEIGHT (default: camera max)")
    p.add_argument("--autofocus", choices=["on", "off"], default=None, help="Force autofocus on/off")
    p.add_argument("--focus", type=int, default=None, help="Manual focus value (with --autofocus off)")
    p.add_argument("--brightness", type=int, default=None, help="Brightness value (driver-specific)")
    p.add_argument("--api-key", default=None, help="OpenAI API key (default: OPENAI_API_KEY env var)")
    p.add_argument("--supabase-url", default=None, help="Supabase URL (default: SUPABASE_URL env var)")
    p.add_argument("--supabase-key", default=None, help="Supabase service_role key (default: SUPABASE_KEY env var)")
    p.add_argument("--no-upload", action="store_true", help="Don't upload anything to Supabase")
    p.add_argument("--sync-interval", type=float, default=5, help="Minutes between backlog retries while idle (default: 5)")
    p.add_argument("--test", action="store_true", help="Run one cycle immediately (no button) and exit")
    p.add_argument("--sync-only", action="store_true", help="Upload any backlog and exit")
    args = p.parse_args()

    args.cap_width = args.cap_height = None
    if args.resolution:
        try:
            args.cap_width, args.cap_height = (int(x) for x in args.resolution.lower().split("x"))
        except ValueError:
            p.error(f"--resolution must be WIDTHxHEIGHT (e.g. 1920x1080), got: {args.resolution}")
    return args


def main():
    args = parse_args()

    bin_dir = Path(args.bin_dir).expanduser().resolve()
    bin_dir.mkdir(parents=True, exist_ok=True)

    supa = make_supabase_client(args)

    if args.sync_only:
        if supa:
            sync_backlog(supa, bin_dir)
        return

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("ERROR: No OpenAI API key. Set OPENAI_API_KEY or pass --api-key.")

    button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)
    solenoid = OutputDevice(SOLENOID_PIN, active_high=SOLENOID_ACTIVE_HIGH, initial_value=False)

    try:
        if args.test:
            run_cycle(args, solenoid, supa, bin_dir, api_key)
            return

        print(f"Ready - waiting for button on GPIO{BUTTON_PIN}. Ctrl+C to stop.")
        last_sync = float("-inf")

        while True:
            button.wait_for_press(timeout=1.0)

            if button.is_pressed:
                print("Button pressed")
                run_cycle(args, solenoid, supa, bin_dir, api_key)
                button.wait_for_release(timeout=10)  # ignore a held button
                print("Ready - waiting for button.")

            elif supa and time.monotonic() - last_sync >= args.sync_interval * 60:
                sync_backlog(supa, bin_dir)
                last_sync = time.monotonic()

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        solenoid.off()


if __name__ == "__main__":
    main()
