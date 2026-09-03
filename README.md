Welcome to my first repo

This is designed to be a battery detection system. It uses two cameras, a Raspberry Pi 5, and GPT-4.0 to take pictures of batteries and identify them based on labels and their general shapes. 

This project uses:
  1. Raspberry Pi 5
  2. x2 webcams
  3. Arduino Mega
  4. Arduino components: LCD, LED, potentiometer, button, and 220 K resistors

In future, there will be:
  1. Scales to measure and track the weight of batteries
  2. Solenoid to activate the bin trap door for the battery bin
  3. Motion-detected light for cameras and user
  4. (maybe) a second or larger LCD to display more data
  5. Potentially another camera

How it works
        -Raspberry Pi 5 runs a lite version of Ubuntu to run scripts off of
        -The Pi 5 runs 2 main scripts:
                1. python_listener.py:
                        -This listens for input from the Arduino and posts a response when the button is pressed. It also helps the Arduino decide what to                                 display on the screen and what type of battery is found. (A more extensive explanation will be shown later)
                2. identify_battery.py:
                        -This Python script takes photos from two cameras and send those images to GPT-4.0 with a prompt to dictate whether the object is a                                 battery? If so, what type? Then it sends the battery image to Supabase, and Supabase publishes the image to a GitHub page.
                         (A more extensive explanation will be shown later)
        - Once the images are sent off to Supabase, is then used in the index.html and print all the data sent.

How to set it up:
        1. Install Ubuntu-lite on the Raspberry Pi 5
        2. ```sudo apt update && sudo apt full-upgrade -y```
        3. Create a folder to host the images and scripts. I used /home/<user>/Destop/BatteryBin
        4. Create a Python environment to use ```sudo apt install python3 <env-name>```
        5. ```pip install opencv-python openai supabase pyserial``` (may need more, but you can see what you need once you run the scripts)
        6. Create a Supabase account if not already
        7. Open SQL editor in Supabase and add the ```shcema.sql```
        8. Go to bucket in Supabase and name new bucket exactly ```battery-photos``` 
        9. Then go to project settings and copy project URL & anon-public API key (save for later)
        10. Create an OpenAI API key and store the API key for later (Note: you will need to add funds to the API for it to work)
        11. Create a github repo for your index.html to be hosted on
        12. Download the ```index.html``` and add it to your repos pages
        13. Then on the Pi 5 run:
        14. ```nano ~/.bashrc``` and add your API keys to the bottom of the file
        15. ```export OPENAI_API_KEY="sk-your-actual-key-here"```
        16. ```export SUPABASE_URL="https://xxxxx.supabase.co"```
        17. ```export SUPABASE_KEY="your-anon-public-key"```
        
        
                
