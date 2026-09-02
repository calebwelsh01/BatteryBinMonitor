#!/usr/bin/env python3
"""
Battery Identifier
-------------------
Captures a photo from your webcam using OpenCV, sends it to the OpenAI
Vision API (GPT-4o / GPT-4o-mini), and asks the model to identify:
  - whether the image contains a battery at all (True/False)
  - the battery type (e.g. AA, AAA, 9V, CR2032 coin cell, 18650 Li-ion, etc.)

Results are written to an XML file containing the battery type and the
photo filename.

Setup:
    pip install opencv-python openai

    Add your API key to ~/.bashrc so it's available in every terminal session:
        nano ~/.bashrc
        # add this line at the bottom:
        export OPENAI_API_KEY="sk-your-actual-key-here"
        # save (Ctrl+O, Enter, Ctrl+X), then reload:
        source ~/.bashrc

    IMPORTANT: .bashrc is only loaded by interactive shells (terminal/SSH).
    If you launch this script by double-clicking it in a file manager or
    from an IDE that wasn't itself opened from a terminal, the variable
    may not be inherited - in that case, run it from a terminal instead,
    or pass the key directly with --api-key.

Usage:
    python identify_battery.py
    python identify_battery.py --camera 1       # use a different camera index
    python identify_battery.py --image path.jpg # skip webcam, use existing image
    python identify_battery.py --xml-output result.xml  # custom XML output path

    # Also push this result straight to the hosted dashboard (requires
    # pip install supabase, and SUPABASE_URL / SUPABASE_KEY set as env vars
    # or passed via --supabase-url / --supabase-key). Use the service_role
    # key here, the same one the standalone uploader script uses.
    python identify_battery.py --upload
"""

import argparse
import base64
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from xml.dom import minidom

import cv2
from openai import OpenAI


def capture_webcam_photo(
    camera_index: int = 0,
    save_path: str = None,
    width: int = None,
    height: int = None,
    autofocus: bool = None,
    focus: int = None,
    brightness: int = None,
) -> str:
    """Capture a single photo from the webcam and save it to disk.

    By default requests the highest resolution the camera supports: most
    drivers clamp an intentionally oversized request down to their actual
    max, rather than erroring out. Pass width/height to request a specific
    resolution instead.

    On Linux (e.g. Raspberry Pi), this opens the camera with the V4L2
    backend and forces MJPG capture. Most USB webcams only expose their
    higher resolutions under MJPG - without it, V4L2 falls back to
    uncompressed YUYV, which is capped much lower by USB bandwidth (often
    ~480p) regardless of what resolution you request. FOURCC has to be set
    before width/height, or the driver may ignore the resolution change.

    autofocus: True to force autofocus on, False to force it off. Leave as
        None to leave the camera's default behavior untouched.
    focus: manual focus value (driver-specific range, often roughly 0-255).
        Only meaningful when autofocus is False. Ignored otherwise.
    brightness: brightness value (driver-specific range, often roughly
        0-255 or -64 to 64 depending on the camera).

    Support for these controls varies by OS/driver - some webcams or
    backends silently ignore properties they don't support.

    Returns the path to the saved image.
    """
    if sys.platform.startswith("linux"):
        cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
    else:
        cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        raise RuntimeError(
            f"Could not open camera index {camera_index}. "
            "Try a different --camera index, or check camera permissions."
        )

    if sys.platform.startswith("linux"):
        # Must happen before width/height are set, or it may be ignored.
        ok = cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        if not ok:
            print("WARNING: camera/driver didn't accept MJPG - resolution may be capped low.")

    if width and height:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    else:
        # Intentionally oversized request - the driver clamps this down to
        # the camera's actual maximum supported resolution.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 9999)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 9999)

    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join(chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)) if fourcc_int else "?"
    print(f"Camera resolution: {actual_width}x{actual_height} (format: {fourcc_str})")

    if autofocus is not None:
        ok = cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if autofocus else 0)
        if not ok:
            print("WARNING: this camera/driver didn't accept the autofocus setting.")
        if autofocus is False and focus is not None:
            ok = cap.set(cv2.CAP_PROP_FOCUS, focus)
            if not ok:
                print("WARNING: this camera/driver didn't accept the manual focus value.")

    if brightness is not None:
        ok = cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
        if not ok:
            print("WARNING: this camera/driver didn't accept the brightness value.")

    # Let the camera adjust exposure/focus for a few frames before capturing.
    frame = None
    for _ in range(10):
        ret, frame = cap.read()
        if not ret:
            cap.release()
            raise RuntimeError("Failed to read frame from webcam.")

    cap.release()

    if save_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"battery_photo_{timestamp}.jpg"

    cv2.imwrite(save_path, frame)
    print(f"Photo captured and saved to: {save_path}")
    return save_path


def encode_image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def identify_battery(image_path: str, api_key: str = None) -> dict:
    """Send the image to OpenAI's vision-capable model and return a dict with:
        - is_battery (bool)
        - battery_type (str)
        - reasoning (str)
    """
    client = OpenAI(api_key=api_key) if api_key else OpenAI()

    b64_image = encode_image_to_base64(image_path)

    prompt = (
        "Is this a battery? If so, what type?\n\n"
        "Respond with ONLY a JSON object (no markdown fences, no extra text) "
        "in exactly this format:\n"
        '{\n'
        '  "is_battery": true or false,\n'
        '  "battery_type": "the battery type if is_battery is true (e.g. AA, '
        '9V, CR2032), or \\"unknown\\" if unclear, or \\"none\\" if not a '
        'battery",\n'
        '  "reasoning": "brief explanation"\n'
        '}'
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",  # use "gpt-4o" for higher accuracy if desired
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}"
                        },
                    },
                ],
            }
        ],
        max_tokens=300,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content

    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Model did not return valid JSON: {e}\nRaw response: {raw_content}"
        )

    # Normalize / validate fields so downstream code can rely on them.
    is_battery = bool(parsed.get("is_battery", False))
    battery_type = str(parsed.get("battery_type", "unknown")).strip()
    reasoning = str(parsed.get("reasoning", "")).strip()

    if not is_battery:
        battery_type = "none"

    return {
        "is_battery": is_battery,
        "battery_type": battery_type,
        "reasoning": reasoning,
    }


def write_result_xml(image_path: str, result: dict, xml_path: str) -> str:
    """Write the identification result to an XML file.

    Includes whether a battery was detected, the battery type, and the
    photo filename. Returns the path to the written XML file.
    """
    root = ET.Element("BatteryIdentification")

    ET.SubElement(root, "PhotoFilename").text = os.path.basename(image_path)
    ET.SubElement(root, "IsBattery").text = str(result["is_battery"]).lower()
    ET.SubElement(root, "BatteryType").text = result["battery_type"]
    ET.SubElement(root, "Reasoning").text = result["reasoning"]
    ET.SubElement(root, "Timestamp").text = datetime.now().isoformat(timespec="seconds")

    # Pretty-print the XML instead of writing it as one long line.
    rough_string = ET.tostring(root, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ")

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(pretty_xml)

    return xml_path


def upload_to_dashboard(image_path: str, result: dict, captured_at: str, supabase_url: str, supabase_key: str) -> str:
    """Push this single image + result straight to the hosted Supabase dashboard.

    Requires the `supabase` package (pip install supabase). Uses upsert on
    photo_filename, so re-running on the same file is safe and won't create
    duplicates. Returns the public URL of the uploaded photo.
    """
    from supabase import create_client

    client = create_client(supabase_url, supabase_key)

    storage_path = os.path.basename(image_path)
    with open(image_path, "rb") as f:
        client.storage.from_("battery-photos").upload(
            storage_path,
            f.read(),
            file_options={"content-type": "image/jpeg", "upsert": "true"},
        )

    public_url = client.storage.from_("battery-photos").get_public_url(storage_path)

    client.table("battery_readings").upsert(
        {
            "photo_filename": storage_path,
            "photo_url": public_url,
            "is_battery": result["is_battery"],
            "battery_type": result["battery_type"],
            "reasoning": result["reasoning"],
            "captured_at": captured_at,
        },
        on_conflict="photo_filename",
    ).execute()

    return public_url


def main():
    parser = argparse.ArgumentParser(description="Identify a battery type from a webcam photo.")
    parser.add_argument("--camera", type=int, default=0, help="Webcam device index (default: 0)")
    parser.add_argument("--resolution", type=str, default=None, help="Manual capture resolution as WIDTHxHEIGHT (e.g. 1920x1080). Default: request the camera's maximum supported resolution.")
    parser.add_argument("--autofocus", type=str, choices=["on", "off"], default=None, help="Force autofocus on or off. Default: leave camera's current setting untouched.")
    parser.add_argument("--focus", type=int, default=None, help="Manual focus value (driver-specific range, often ~0-255). Only applied when --autofocus off is also set.")
    parser.add_argument("--brightness", type=int, default=None, help="Brightness value (driver-specific range, often ~0-255 or -64 to 64).")
    parser.add_argument("--image", type=str, default=None, help="Path to an existing image instead of using the webcam")
    parser.add_argument("--api-key", type=str, default=None, help="OpenAI API key (defaults to OPENAI_API_KEY env var)")
    parser.add_argument("--xml-output", type=str, default=None, help="Path to write the result XML file (default: <image_basename>.xml)")
    parser.add_argument("--upload", action="store_true", help="Also push this result straight to the hosted Supabase dashboard (requires pip install supabase)")
    parser.add_argument("--supabase-url", type=str, default=None, help="Supabase project URL (defaults to SUPABASE_URL env var; only needed with --upload)")
    parser.add_argument("--supabase-key", type=str, default=None, help="Supabase service_role key (defaults to SUPABASE_KEY env var; only needed with --upload)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(
            "ERROR: No OpenAI API key found. Set the OPENAI_API_KEY environment "
            "variable or pass --api-key.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        if args.image:
            image_path = args.image
            if not os.path.isfile(image_path):
                print(f"ERROR: Image not found: {image_path}", file=sys.stderr)
                sys.exit(1)
        else:
            print("Opening webcam... position the battery clearly in view.")
            cap_width = cap_height = None
            if args.resolution:
                try:
                    cap_width, cap_height = (int(x) for x in args.resolution.lower().split("x"))
                except ValueError:
                    print(f"ERROR: --resolution must be WIDTHxHEIGHT (e.g. 1920x1080), got: {args.resolution}", file=sys.stderr)
                    sys.exit(1)
            image_path = capture_webcam_photo(
                camera_index=args.camera,
                width=cap_width,
                height=cap_height,
                autofocus=(None if args.autofocus is None else args.autofocus == "on"),
                focus=args.focus,
                brightness=args.brightness,
            )

        print("Sending image to OpenAI for identification...")
        result = identify_battery(image_path, api_key=api_key)

        print("\n=== Battery Identification ===")
        print(f"Is battery: {result['is_battery']}")
        print(f"Battery type: {result['battery_type']}")
        print(f"Reasoning: {result['reasoning']}")

        xml_path = args.xml_output or f"{os.path.splitext(image_path)[0]}.xml"
        write_result_xml(image_path, result, xml_path)
        print(f"\nResult written to: {xml_path}")

        if args.upload:
            supabase_url = args.supabase_url or os.environ.get("SUPABASE_URL")
            supabase_key = args.supabase_key or os.environ.get("SUPABASE_KEY")
            if not supabase_url or not supabase_key:
                print(
                    "WARNING: --upload was set but SUPABASE_URL/SUPABASE_KEY were not "
                    "found (env vars or --supabase-url/--supabase-key). Skipping upload; "
                    "the local photo and XML were still saved.",
                    file=sys.stderr,
                )
            else:
                print("Uploading to hosted dashboard...")
                captured_at = datetime.now().isoformat(timespec="seconds")
                upload_to_dashboard(image_path, result, captured_at, supabase_url, supabase_key)
                print("Uploaded to dashboard.")

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
