# Battery Detection System

Welcome to my first GitHub repository!

This project is a **battery detection and sorting system** designed to identify batteries using computer vision and AI.

The system uses **two cameras, a Raspberry Pi 5, an Arduino Mega, and OpenAI's GPT-4.0 vision capabilities** to photograph batteries and determine whether an object is a battery and, if so, what type of battery it is.

The project is designed to eventually become a more automated battery collection and sorting system.

---

## Current Hardware

The current system uses:

1. **Raspberry Pi 5**
2. **2× USB webcams**
3. **Arduino Mega**
4. **16×2 HD44780 LCD**
5. **10KΩ potentiometer**
6. **LED**
7. **Push button**
8. **~220Ω resistor for the LED**
9. **220KΩ resistors** used by the Arduino circuitry

---

## Planned Features

There are several features planned for future versions of the project:

* **Digital scales**

  * Measure and record the weight of each battery
  * Track battery weights over time

* **Solenoid-controlled bin**

  * Automatically open a trap door to sort or dispose of batteries

* **Motion-activated lighting**

  * Automatically illuminate the cameras and user area when motion is detected

* **Larger LCD display**

  * Display additional information about detected batteries

* **Additional camera**

  * Potentially add a third camera for improved identification

* **YOLO26 compatibility for future use with custom training data**

  * Potentially add customer data to better identify swollen or broken batteries going in and training with custom datasets

---

# Wiring

The Arduino Mega is responsible for controlling the LCD, LED, and push button.

## LCD Wiring

The LCD uses a standard **16×2 HD44780 display in 4-bit mode**.

| LCD Pin       | Function        | Connects To                                |
| ------------- | --------------- | ------------------------------------------ |
| 1 (VSS)       | GND             | Mega GND                                   |
| 2 (VDD)       | +5V             | Mega 5V                                    |
| 3 (V0)        | Contrast        | Middle pin of 10KΩ potentiometer           |
| 4 (RS)        | Register Select | Mega D8                                    |
| 5 (RW)        | Read/Write      | Mega GND                                   |
| 6 (E)         | Enable          | Mega D9                                    |
| 7–10 (D0–D3)  | Data            | Not connected                              |
| 11 (D4)       | Data            | Mega D10                                   |
| 12 (D5)       | Data            | Mega D11                                   |
| 13 (D6)       | Data            | Mega D12                                   |
| 14 (D7)       | Data            | Mega D13                                   |
| 15 (A / LED+) | Backlight +     | Mega 5V through ~220Ω resistor if required |
| 16 (K / LED-) | Backlight -     | Mega GND                                   |

### LCD Contrast Potentiometer

The 10KΩ potentiometer is used to control the LCD contrast.

Connect it as follows:

| Potentiometer Connection | Connects To    |
| ------------------------ | -------------- |
| Outer pin                | Mega 5V        |
| Middle pin               | LCD V0 (Pin 3) |
| Outer pin                | Mega GND       |

The two outer pins can be swapped; this will simply reverse the direction of the contrast adjustment.

---

## LED Wiring

The LED is used as an indicator and is connected to a digital output on the Arduino Mega.

```text
Mega D4 ─── ~220Ω resistor ─── LED Anode (+)
                                LED Cathode (-)
                                      │
                                      │
                                   Mega GND
```

### Connections

* **LED anode (+)** → ~220Ω resistor → **Mega D4**
* **LED cathode (-)** → **Mega GND**

The resistor is required to limit the current through the LED and prevent damage.

---

## Push Button Wiring

The push button is connected to **digital pin D2** and GND.

```text
Mega D2 ───── Push Button ───── Mega GND
```

### Connections

* One side of the button → **Mega D2**
* Other side of the button → **Mega GND**

The Arduino can use its internal pull-up resistor, meaning an external resistor is not required for the button.

For example:

```cpp
pinMode(2, INPUT_PULLUP);
```

With this configuration:

* Button **not pressed** → `HIGH`
* Button **pressed** → `LOW`

---

## Arduino Pin Summary

| Component       | Arduino Mega Pin |
| --------------- | ---------------- |
| LCD RS          | D8               |
| LCD Enable      | D9               |
| LCD D4          | D10              |
| LCD D5          | D11              |
| LCD D6          | D12              |
| LCD D7          | D13              |
| LED             | D4               |
| Push Button     | D2               |
| LCD VSS         | GND              |
| LCD VDD         | 5V               |
| LCD RW          | GND              |
| LCD Backlight + | 5V               |
| LCD Backlight - | GND              |

---

# How It Works

The Raspberry Pi 5 runs a lightweight Ubuntu installation and handles the main Python programs.

The system currently has **two primary Python scripts**.

## `python_listener.py`

This script communicates with the Arduino Mega over USB serial.

Its main functions are:

* Listen for input from the Arduino
* Detect when the user presses the button
* Trigger the battery identification process
* Send information back to the Arduino
* Tell the Arduino what information should be displayed on the LCD
* Help determine what type of battery has been detected

> A more detailed explanation of this script will be added in the future.

---

## `identify_battery.py`

This script handles the actual battery identification process.

The general process is:

1. Capture an image using **Camera 1**
2. Capture an image using **Camera 2**
3. Send both images to OpenAI's vision model
4. Ask the model whether the object is a battery
5. If it is a battery, determine what type of battery it is
6. Upload the battery images and associated information to **Supabase**
7. Supabase stores the data and images
8. The GitHub-hosted `index.html` page retrieves the information and displays it

> A more detailed explanation of this script will be added in the future.

---

# Supabase

Supabase is used to store the battery images and associated data.

The project uses a Supabase storage bucket named:

```text
battery-photos
```

The database schema is provided in:

```text
schema.sql
```

The GitHub webpage then retrieves the stored information and displays the detected batteries.

---

# Setup

## 1. Install Ubuntu

Install a lightweight version of Ubuntu on the Raspberry Pi 5.

Once Ubuntu is installed, update the system:

```bash
sudo apt update
sudo apt full-upgrade -y
```

---

## 2. Create the Project Directory

Create a directory for the project.

For example:

```bash
mkdir -p ~/Desktop/BatteryBin
cd ~/Desktop/BatteryBin
```

Place the project files inside this directory.

---

## 3. Install Python

Install Python and the required packages:

```bash
sudo apt install python3 python3-pip python3-venv -y
```

Create a Python virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
source python_env~/bin/activate
```

---

## 4. Install Python Dependencies

Install the required Python packages:

```bash
pip install opencv-python openai supabase pyserial
```

Additional packages may be required depending on the version of the scripts.

If a script reports a missing Python module, install the required package using:

```bash
pip install <package-name>
```

---

# Supabase Setup

## 5. Create a Supabase Project

Create a Supabase account and create a new project.

---

## 6. Configure the Database

Open the **SQL Editor** in Supabase.

Run the SQL contained in:

```text
schema.sql
```

This will create the required database structure.

---

## 7. Create the Storage Bucket

Go to **Storage** in Supabase and create a new bucket.

The bucket must be named exactly:

```text
battery-photos
```

---

## 8. Get Your Supabase Credentials

Go to your Supabase project settings and find:

* Project URL
* Anon/Public API key

Keep these values somewhere safe. They will be required when configuring the Raspberry Pi.

---

# OpenAI Setup

## 9. Create an OpenAI API Key

Create an OpenAI API key and keep it somewhere secure.

> **Important:** API usage requires billing/credits to be configured on your OpenAI account.

Do **not** commit your API key to GitHub.

---

# GitHub Pages Setup

## 10. Create a GitHub Repository

Create a GitHub repository that will host the project's web interface.

---

## 11. Add `index.html`

Add the provided:

```text
index.html
```

file to the GitHub repository.

Enable **GitHub Pages** for the repository so that the webpage can be accessed through the internet.

The webpage will retrieve battery information from Supabase and display it.

---

# Configure Environment Variables

Rather than putting API keys directly into the Python scripts, the project uses environment variables.

On the Raspberry Pi, open your Bash configuration:

```bash
nano ~/.bashrc
```

Add the following to the bottom of the file:

```bash
export OPENAI_API_KEY="sk-your-actual-key-here"
export SUPABASE_URL="https://xxxxx.supabase.co"
export SUPABASE_KEY="your-anon-public-key"
```

Save the file and reload your Bash configuration:

```bash
source ~/.bashrc
```

You can check that the variables exist with:

```bash
echo $OPENAI_API_KEY
echo $SUPABASE_URL
echo $SUPABASE_KEY
```

**Be careful when displaying your API key in a terminal or sharing screenshots.**

---

# Arduino Serial Port

`python_listener.py` communicates with the Arduino through a serial connection.

You will need to determine which serial port your Arduino is connected to.

You can check connected USB devices with:

```bash
lsusb
```

You can also check available serial devices with:

```bash
ls /dev/ttyUSB*
```

or:

```bash
ls /dev/ttyACM*
```

For example, my Arduino was connected as:

```text
/dev/ttyUSB0
```

The serial port is configured in `python_listener.py`:

```python
SERIAL_PORT = "/dev/ttyUSB0"
```

Change this value if your Arduino is using a different port.

For example:

```python
SERIAL_PORT = "/dev/ttyACM0"
```

---

# Camera Configuration

The two webcams are identified by their camera indexes.

You may need to determine which indexes Linux has assigned to your webcams.

The `identify_battery.py` script is launched using arguments similar to:

```bash
python3 identify_battery.py --camera 0 --camera2 2 --upload
```

In this example:

* `--camera 0` → Camera 1
* `--camera2 2` → Camera 2
* `--upload` → Upload the captured images to Supabase

Your camera indexes may be different.

For example, your cameras could be:

```bash
python3 identify_battery.py --camera 1 --camera2 3 --upload
```

Use the available `/dev/video*` devices to help determine which cameras are connected.

---

# Running the System

Once everything is configured, the general workflow is:

```text
           ┌──────────────┐
           │ Arduino Mega │
           └──────┬───────┘
                  │
             Button Press
                  │
                  ▼
        ┌───────────────────┐
        │ python_listener.py│
        └─────────┬─────────┘
                  │
                  ▼
        ┌───────────────────┐
        │ identify_battery  │
        │       .py         │
        └─────────┬─────────┘
                  │
          ┌───────┴───────┐
          ▼               ▼
     ┌─────────┐     ┌─────────┐
     │ Camera 1│     │ Camera 2│
     └────┬────┘     └────┬────┘
          │               │
          └───────┬───────┘
                  │
                  ▼
          ┌──────────────┐
          │    OpenAI    │
          │    Vision    │
          └──────┬───────┘
                 │
                 ▼
          Battery detected
                 │
                 ▼
          ┌──────────────┐
          │   Supabase   │
          └──────┬───────┘
                 │
                 ▼
          ┌──────────────┐
          │  GitHub Page │
          │  index.html  │
          └──────────────┘
```

---

# Project Structure

The project will generally look something like:

```text
BatteryBin/
├── python_listener.py
├── identify_battery.py
├── schema.sql
├── index.html
├── README.md
└── .venv/
```

---

# Future Development

This project is still under development.

Future versions will focus on making the system more automated and improving the amount of information recorded for each battery.

Potential additions include:

* Battery weight measurement
* Automatic battery sorting
* Solenoid-controlled trap door
* Motion detection
* Automatic lighting
* Additional cameras
* Larger LCD display
* More detailed battery information
* Battery history and statistics
* Improved AI identification
* Automatic battery type categorisation

---


