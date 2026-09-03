#include <LiquidCrystal.h>

// RS, E, D4, D5, D6, D7
LiquidCrystal lcd(8, 9, 10, 11, 12, 13);

const int BUTTON_PIN = 2;
const int LED_PIN = 4;

bool lastButtonState = HIGH;
String batteryResult = "Press button";

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

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
      drawScreen();
    }
  }
}

void drawScreen() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Battery:");
  lcd.setCursor(0, 1);
  lcd.print(batteryResult);
}