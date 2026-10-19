# BatteryBin — AI Battery Detection System

BatteryBin is a battery detection system that uses computer vision and AI to photograph an item, determine whether it is a battery, and identify its type. It runs on a **Raspberry Pi 5**, uses one or two USB webcams, sends images to an OpenAI vision model, and stores the resulting photos and identification data in Supabase for display by the project's web interface.

The controller has been consolidated into a single Python program, `batterybin.py`. The Arduino Mega, serial connection, and 16×2 LCD used in earlier versions are no longer part of the current system.

## How it works

1. The user presses the button connected to the Raspberry Pi.
2. BatteryBin captures images from one or two USB webcams.
3. The images are sent to an OpenAI vision model to determine whether the item is a battery and, if so, identify its type.
4. The program saves the identification result as an XML file beside the primary photo.
5. The primary photo and its result are uploaded to Supabase.
6. If a battery is detected, the Raspberry Pi pulses the solenoid to operate the trap door.
7. If an upload fails, the photo/XML pair is kept for a later retry. While the system is idle, pending uploads are retried at the configured interval.

Identification results and status messages are printed to the terminal and can be viewed in the systemd journal when running as a service.

## Current hardware

- Raspberry Pi 5
- One or two USB webcams
- Push button to start a detection cycle
- 12 V solenoid for the trap door
- Logic-level N-channel MOSFET or suitable relay module to switch the solenoid
- 1 kΩ gate resistor and 10 kΩ gate pull-down resistor when using the MOSFET circuit
- SS54 Schottky diode for solenoid flyback protection
- Separate 12 V supply for the solenoid

### Removed from the current version

The following components were used in earlier versions but are no longer required by the current controller:

- Arduino Mega
- Arduino-to-Raspberry Pi USB serial connection
- 16×2 HD44780 LCD and contrast potentiometer
- Arduino indicator LED and associated wiring

## Raspberry Pi 5 wiring

GPIO numbers below use **BCM numbering**, as used by `batterybin.py`. Physical pin numbers refer to the Raspberry Pi's 40-pin header.

| Device | BCM GPIO | Physical pin | Connection / notes |
|---|---:|---:|---|
| Push button | GPIO17 | 11 | Connect the other button terminal to GND (physical pin 9). The program uses an internal pull-up, so no external button resistor is needed. |
| Solenoid driver control | GPIO27 | 13 | Connect to the logic-level MOSFET gate or relay input. Connect the driver ground to Raspberry Pi GND (for example, physical pin 14). |

The pin assignments can be changed using `BUTTON_PIN` and `SOLENOID_PIN` near the top of `batterybin.py`. For an active-low relay board, set `SOLENOID_ACTIVE_HIGH = False`.

### Solenoid safety

- **Never power the solenoid directly from a Raspberry Pi GPIO pin.** GPIO pins are 3.3 V only and are not 5 V tolerant.
- Use a suitably rated logic-level N-channel MOSFET or relay driver and a separate supply appropriate for the solenoid.
- When using a MOSFET, connect the solenoid between the external supply's positive terminal and the MOSFET drain, and connect the MOSFET source to ground.
- Fit a flyback diode across the solenoid coil. For the SS54 diode, connect the **striped cathode to +12 V / solenoid positive** and the anode to the MOSFET drain / solenoid negative.
- Connect the external supply ground and Raspberry Pi ground together so the control signal has a common reference.
- Confirm the MOSFET, relay, wiring, power supply, and diode are rated for the solenoid's voltage and current.

## Software and project structure

The current controller is `batterybin.py`. It combines the responsibilities previously handled by `python_listener.py`, `identify_battery.py`, and `upload_battery_data.py`:

- Button monitoring and detection-cycle control
- Webcam capture
- OpenAI vision identification
- XML result creation
- Supabase upload
- Retrying photo/XML pairs that have not uploaded successfully

A typical project directory may look like this:

```text
BatteryBin/
├── batterybin.py
├── schema.sql
├── index.html                 # web interface, if maintained in this repository
├── README.md
├── .env                       # local secrets; do not commit
├── .uploaded_state.json       # upload state; do not commit
└── python_env/                # Python virtual environment
```

The precise files in the repository may vary. The script saves photos and XML results to `--bin-dir`, which defaults to the script's own directory.

## Setup

These instructions assume Ubuntu or another compatible Linux installation on the Raspberry Pi 5.

### 1. Update the Raspberry Pi and install system packages

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install python3 python3-pip python3-venv swig liblgpio-dev python3-dev -y
```

The `swig`, `liblgpio-dev`, and `python3-dev` packages are needed if `lgpio` must be built in the virtual environment.

### 2. Create and activate the Python environment

From the project directory:

```bash
python3 -m venv python_env
source python_env/bin/activate
pip install --upgrade pip
pip install opencv-python openai supabase gpiozero lgpio
```

Check that `lgpio` imports correctly:

```bash
python -c "import lgpio; print('lgpio OK')"
```

The Raspberry Pi 5 uses `lgpio` as the GPIO backend for `gpiozero`; `RPi.GPIO` is not supported as the Pi 5 backend. If `lgpio` fails to build, install the system package instead:

```bash
sudo apt install python3-lgpio
```

If using the system package from the virtual environment, set `include-system-site-packages = true` in `python_env/pyvenv.cfg`.

### 3. Allow the service user to access GPIO

For a service running as the `staff` user:

```bash
sudo usermod -aG gpio staff
```

Log out and back in (or reboot) for the group change to take effect.

### 4. Configure OpenAI and Supabase

Create an OpenAI API key and a Supabase project. OpenAI API usage may require billing or credits to be enabled.

The program reads these environment variables:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key used for vision identification |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase API key used by the uploader; use the key required by your configured upload policies and keep it secret |

The project uses a Supabase Storage bucket named `battery-photos`. If the database schema is needed, run the SQL in `schema.sql` using the Supabase SQL Editor. The web interface can retrieve stored battery information and display it.

Create a local `.env` file in the project directory. For example:

```dotenv
OPENAI_API_KEY=your-openai-api-key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-key
```

Do not commit `.env` or paste its contents into public logs, screenshots, or issues. Add at least the following to `.gitignore`:

```gitignore
.env
.uploaded_state.json
python_env/
```

**Security note:** An earlier version of `upload_battery_data.py` contained a hard-coded Supabase `service_role` key. If that key was ever committed or shared, regenerate it in Supabase. A `service_role` key bypasses row-level security and must never be committed to the repository. Use environment variables or command-line flags for credentials, and use the least-privileged key compatible with the application's upload policies.

### 5. Configure the systemd service environment

`systemd` does not automatically read `~/.bashrc`. Configure the service to load the `.env` file directly. Adjust paths and the service name to match your installation.

Example service settings:

```ini
[Service]
User=staff
WorkingDirectory=/home/staff/Desktop/BatteryBin
EnvironmentFile=/home/staff/Desktop/BatteryBin/.env
ExecStart=/home/staff/Desktop/BatteryBin/python_env/bin/python /home/staff/Desktop/BatteryBin/batterybin.py
```

If you already have a service installed, keep its existing unit configuration and update the relevant paths and environment settings. After changing the unit, reload systemd and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart battery-listener
```

The service name above follows the existing project notes; use the actual unit name on your Raspberry Pi.

## Running BatteryBin

Activate the environment and run the script from the project directory.

```bash
source python_env/bin/activate
python batterybin.py
```

Available modes:

| Command | Purpose |
|---|---|
| `python batterybin.py` | Normal mode: wait for a button press and process each detection cycle. |
| `python batterybin.py --test` | Run a full detection cycle immediately without waiting for the button. |
| `python batterybin.py --sync-only` | Attempt to upload pending items, then exit. |
| `python batterybin.py --camera2 -1` | Use one camera instead of the default two-camera setup. |
| `python batterybin.py --no-upload` | Run locally without uploading to Supabase. |

Other supported options include `--bin-dir`, `--camera`, `--resolution WxH`, `--autofocus on|off`, `--focus`, `--brightness`, `--sync-interval`, `--api-key`, `--supabase-url`, and `--supabase-key`. Run `python batterybin.py --help` to check the options supported by the version installed on your device.

The second camera defaults to index `2`, matching the earlier listener configuration. Use `--camera2 -1` if you want to run with one camera. Camera indexes can differ between devices, so check the available `/dev/video*` devices if a camera cannot be opened.

### Upload retry behaviour

If a direct upload fails, the local photo/XML pair remains available for a later retry. While the system is idle, BatteryBin checks for pending uploads at the interval set by `--sync-interval` (default: 5 minutes). The `.uploaded_state.json` file tracks upload state and should not be committed to Git.

## Web interface and Supabase data

Supabase stores the battery photos and associated identification data. The storage bucket is named `battery-photos`; the database structure is documented in `schema.sql` when that file is present in the repository.

The project's `index.html` web interface can retrieve and display battery records from Supabase. If hosting it with GitHub Pages, configure the repository's Pages settings and ensure that any data access uses appropriate Supabase policies. Never put a privileged service-role key in client-side HTML or JavaScript.

## Troubleshooting

### `gpiozero.exc.BadPinFactory: Unable to load any default pin factory!`

Confirm that `lgpio` is installed in the same Python environment used to run the script:

```bash
source python_env/bin/activate
python -c "import lgpio; print('lgpio OK')"
```

To expose the underlying GPIO backend error, try:

```bash
GPIOZERO_PIN_FACTORY=lgpio python batterybin.py --test
```

### `error: command 'swig' failed: No such file or directory`

Install the build dependencies, then retry the package installation:

```bash
sudo apt install swig liblgpio-dev python3-dev
source python_env/bin/activate
pip install lgpio
```

### Permission denied on `/dev/gpiochip*`

Add the account running BatteryBin to the `gpio` group and log in again:

```bash
sudo usermod -aG gpio staff
```

Replace `staff` if your service runs under a different user.

### The script works in a terminal but not as a service

Check that the service uses the same virtual environment where the dependencies were installed, that `WorkingDirectory` points to the project directory, and that `EnvironmentFile` points to the `.env` file. Review the service logs:

```bash
sudo journalctl -u battery-listener -f
```

Use the correct unit name if it differs from `battery-listener`.

### A camera cannot be opened

Check which video devices are present:

```bash
ls /dev/video*
```

Then test the camera indexes configured with `--camera` and `--camera2`. If only one webcam is connected or available, use `--camera2 -1`.

### Uploads are failing

Check that `SUPABASE_URL` and `SUPABASE_KEY` are set correctly, that the `battery-photos` bucket exists, and that the configured key and Supabase policies permit the upload. Failed photo/XML pairs should remain in the local backlog for retry. Do not share API keys when posting logs for help.

## Planned future improvements

These are possible future additions and are **not described as currently implemented**:

- Digital scales to measure and record battery weight
- Motion-activated lighting
- An additional camera
- Improved battery categorisation and more detailed battery history/statistics
- Exploring a custom-trained YOLO model to identify damaged, swollen, or broken batteries

## Contributing and maintenance

BatteryBin is under development. When changing hardware or software, update this README to reflect the tested behaviour and current wiring. Keep credentials and local upload-state files out of version control.
