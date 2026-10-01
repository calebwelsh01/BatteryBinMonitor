#include <LiquidCrystal.h>

// RS, E, D4, D5, D6, D7
LiquidCrystal lcd(8, 9, 10, 11, 12, 13);

const int BUTTON_PIN = 2;
const int LED_PIN = 4;
const int PULSE_PIN = 7;

const unsigned long PULSE_DURATION = 2000; // ms pin 7 stays HIGH
unsigned long pulseStartTime = 0;
bool pulseActive = false;

bool lastButtonState = HIGH;
String batteryResult = "Press button";
String guessResult = "--";

const unsigned long DISPLAY_INTERVAL = 6000; // ms per screen
unsigned long lastSwitchTime = 0;
bool showingGuess = false; // false = battery type screen, true = guess screen

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  pinMode(PULSE_PIN, OUTPUT);
  digitalWrite(PULSE_PIN, LOW);

  lcd.begin(16, 2);
  drawScreen();
}

void loop() {
  bool currentState = digitalRead(BUTTON_PIN);
  if (currentState == LOW && lastButtonState == HIGH) {
    delay(30);
    if (digitalRead(BUTTON_PIN) == LOW) {
      Serial.println("REQUEST_BATTERY");
      batteryResult = "Checking...";
      guessResult = "--";
      showingGuess = false;
      lastSwitchTime = millis();
      drawScreen();
    }
  }
  lastButtonState = currentState;

  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line == "UPLOAD_START") {
      digitalWrite(LED_PIN, HIGH);
    }
    else if (line == "UPLOAD_DONE") {
      digitalWrite(LED_PIN, LOW);
    }
    else if (line.startsWith("BATTERY:")) {
      batteryResult = line.substring(8);
      showingGuess = false;
      lastSwitchTime = millis();
      drawScreen();
      startPulse();
    }
    else if (line.startsWith("GUESS:")) {
      guessResult = line.substring(6);
      startPulse();
    }
  }

  // Turn pin 7 off once the pulse time has passed (non-blocking)
  if (pulseActive && millis() - pulseStartTime >= PULSE_DURATION) {
    digitalWrite(PULSE_PIN, LOW);
    pulseActive = false;
  }

  // Every DISPLAY_INTERVAL, flip between the battery type screen and the
  // guess/prediction screen. Non-blocking so the button and serial reads
  // above still get checked every loop.
  if (millis() - lastSwitchTime >= DISPLAY_INTERVAL) {
    showingGuess = !showingGuess;
    lastSwitchTime = millis();
    drawScreen();
  }
}

void drawScreen() {
  lcd.clear();
  lcd.setCursor(0, 0);
  if (showingGuess) {
    lcd.print("Guess:");
    lcd.setCursor(0, 1);
    lcd.print(guessResult);
  } else {
    lcd.print("Battery:");
    lcd.setCursor(0, 1);
    lcd.print(batteryResult);
  }
}

void startPulse() {
  digitalWrite(PULSE_PIN, HIGH);
  pulseStartTime = millis();
  pulseActive = true;
}
