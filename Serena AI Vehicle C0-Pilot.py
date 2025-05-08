import sys
import time
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QLabel, QVBoxLayout, QWidget, QHBoxLayout, QTextEdit, QComboBox
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QLinearGradient, QBrush, QPalette, QPixmap
import pyttsx3
import speech_recognition as sr
import requests
import pytz
from datetime import datetime, timedelta
import google.generativeai as genai
import random
import sympy as sp
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application
from gtts import gTTS
import pygame
import tempfile
from concurrent.futures import ThreadPoolExecutor

os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts=false"

GENAI_API_KEY = "YOUR API KEY (EG: GEMINI API KEY)"  # Replace with your actual key
genai.configure(api_key=GENAI_API_KEY)
WEATHER_API_KEY = "5bf657e0eae076b99ad1f0e59a6c4358"

GTTS_LANGUAGES = {
    "en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "es": "Spanish",
    "fr": "French", "de": "German", "ja": "Japanese", "zh-cn": "Chinese (Simplified)",
    "ru": "Russian", "ar": "Arabic", "bn": "Bengali", "gu": "Gujarati", "kn": "Kannada",
    "ml": "Malayalam", "mr": "Marathi", "pa": "Punjabi", "ur": "Urdu"
}

initial_car_data = {
    "speed": 0, "battery": 80, "status": "Parked", "trip_distance": 0, "trip_time": 0, "avg_speed": 0,
    "tire_pressure": 2.5, "engine_temp": 85, "seatbelt": "Off"
}
car_data = initial_car_data.copy()

speaking = False
busy = False
response_lang = "en"

pygame.mixer.init()
engine = pyttsx3.init()
voices = engine.getProperty('voices')
engine.setProperty('voice', voices[1].id if len(voices) > 1 else voices[0].id)
engine.setProperty('rate', 150)
engine.setProperty('volume', 0.9)

class AudioThread(QThread):
    finished = pyqtSignal()

    def _init_(self, text, lang):
        super()._init_()
        self.text = text
        self.lang = lang

    def run(self):
        global speaking
        speaking = True
        try:
            if self.lang == "en":
                print(f"Speaking English: {self.text}")
                engine.say(self.text)
                engine.runAndWait()
            else:
                print(f"Generating {self.lang} audio: {self.text}")
                tts = gTTS(text=self.text, lang=self.lang, slow=False)
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                tts.save(temp_file.name)
                temp_file.close()
                sound = pygame.mixer.Sound(temp_file.name)
                sound.play()
                while pygame.mixer.get_busy():
                    time.sleep(0.1)
                sound.stop()  # Explicitly stop to release the file
                time.sleep(0.5)  # Give Windows a moment to release the handle
                os.unlink(temp_file.name)
        except Exception as e:
            print(f"AudioThread error: {str(e)}")
        finally:
            speaking = False
            self.finished.emit()

class ManualSpeechThread(QThread):
    command_signal = pyqtSignal(str, str)
    error_signal = pyqtSignal(str)

    def run(self):
        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                print("Serena AI: Listening...")
                recognizer.adjust_for_ambient_noise(source, duration=1.5)
                audio = recognizer.listen(source, timeout=10, phrase_time_limit=5)
            for lang in ["en-US", "hi-IN", "te-IN"]:
                try:
                    command = recognizer.recognize_google(audio, language=lang).lower()
                    detected_lang = lang.split("-")[0]
                    print(f"You said ({detected_lang}): {command}")
                    self.command_signal.emit(command, detected_lang)
                    return
                except sr.UnknownValueError:
                    continue
            self.error_signal.emit("Sorry, I didn’t catch that.")
        except sr.WaitTimeoutError:
            self.error_signal.emit("Sorry, I didn’t hear you in time. Try again.")
        except sr.RequestError:
            self.error_signal.emit("Speech service issue.")
        except Exception as e:
            self.error_signal.emit(f"Error: {str(e)}")

def call_genai_api(command):
    try:
        model = genai.GenerativeModel('gemini-1.5-pro')
        response = model.generate_content(f"You are Serena AI, an intelligent co-pilot for vehicles. Respond to: {command}")
        return response.text.replace("*", "").strip()
    except Exception as e:
        return f"Error: Unable to connect to Generative AI API - {str(e)}"

def get_weather(city):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            tz_offset = data["timezone"]
            sunrise_utc = datetime.utcfromtimestamp(data["sys"]["sunrise"]).replace(tzinfo=pytz.utc)
            sunset_utc = datetime.utcfromtimestamp(data["sys"]["sunset"]).replace(tzinfo=pytz.utc)
            local_sunrise = sunrise_utc + timedelta(seconds=tz_offset)
            local_sunset = sunset_utc + timedelta(seconds=tz_offset)
            weather_info = (
                f"📍 {data['name']}, {data['sys']['country']}\n"
                f"🌎 Latitude: {data['coord']['lat']}, Longitude: {data['coord']['lon']}\n"
                f"🌡 Temperature: {data['main']['temp']}°C (Feels like {data['main']['feels_like']}°C)\n"
                f"💨 Wind: {data['wind']['speed']} m/s ({deg_to_direction(data['wind']['deg'])})\n"
                f"☁ Cloud Cover: {data['clouds']['all']}%\n"
                f"💧 Humidity: {data['main']['humidity']}%\n"
                f"👁 Visibility: {data['visibility'] / 1000} km\n"
                f"📊 Pressure: {data['main']['pressure']} hPa\n"
                f"🌅 Sunrise: {local_sunrise.strftime('%H:%M:%S')}\n"
                f"🌇 Sunset: {local_sunset.strftime('%H:%M:%S')}\n"
                f"🌤 Condition: {data['weather'][0]['description'].capitalize()}"
            )
            return weather_info
        return f"Couldn’t fetch weather data for {city}."
    except requests.exceptions.RequestException:
        return "Weather service unavailable."

def deg_to_direction(deg):
    directions = ["North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West"]
    index = round(deg / 45) % 8
    return directions[index]

def simulate_car_data():
    global car_data
    if car_data["status"] == "Driving":
        car_data["speed"] += random.uniform(-2, 5)
        car_data["speed"] = max(0, min(120, car_data["speed"]))
        car_data["battery"] -= random.uniform(0, 0.05)
        car_data["trip_distance"] += car_data["speed"] / 3600
        car_data["trip_time"] += 1
        car_data["avg_speed"] = (car_data["trip_distance"] / (car_data["trip_time"] / 3600)) if car_data["trip_time"] > 0 else 0
        car_data["tire_pressure"] += random.uniform(-0.02, 0.02)
        car_data["engine_temp"] += random.uniform(-1, 2)
        car_data["seatbelt"] = "On" if random.random() > 0.1 else "Off"
    elif car_data["status"] == "Idling":
        car_data["speed"] = 0
        car_data["battery"] -= random.uniform(0, 0.01)
        car_data["engine_temp"] += random.uniform(0, 0.5)
    else:
        car_data["speed"] = 0
    car_data["battery"] = max(0, min(100, car_data["battery"]))
    car_data["tire_pressure"] = max(2.0, min(3.0, car_data["tire_pressure"]))
    car_data["engine_temp"] = max(20, min(110, car_data["engine_temp"]))

def calculate_math(command):
    try:
        if any(op in command for op in ['+', '-', '*', '/', 'plus', 'minus', 'times', 'divided by']) and any(c.isdigit() for c in command):
            command = command.replace("plus", "+").replace("minus", "-").replace("times", "*").replace("divided by", "/")
            expr = ''.join(c for c in command if c.isdigit() or c in '+-*/(). ')
            result = eval(expr, {"_builtins_": {}})
            return f"The result is {result}"
        elif "solve" in command or "x" in command or "equation" in command:
            expr = command.split("solve")[-1].strip() if "solve" in command else command
            x = sp.Symbol('x')
            transformations = standard_transformations + (implicit_multiplication_application,)
            eq = parse_expr(expr.split('=')[0], transformations=transformations) - parse_expr(expr.split('=')[1], transformations=transformations) if '=' in expr else parse_expr(expr, transformations=transformations)
            if '=' in expr:
                solutions = sp.solve(eq, x)
                return f"The solutions are {', '.join(str(sol) for sol in solutions)}"
            else:
                result = eq.evalf()
                return f"The result is {result}"
    except Exception as e:
        return f"Sorry, I couldn’t calculate that: {str(e)}"

class SerenaAIWindow(QMainWindow):
    def _init_(self):
        super()._init_()
        self.setWindowTitle("Serena AI - KL University")
        self.setGeometry(100, 100, 1000, 600)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.is_day_mode = True
        self.tesla_font = QFont("Helvetica Neue", 20, QFont.Bold)
        self.tesla_font_small = QFont("Helvetica Neue", 16, QFont.Bold)
        self.last_update = {}
        self.audio_threads = []

        self.logo_label = QLabel(self)
        pixmap = QPixmap(r"D:\SERENA AI\Kl University-01.jpg")
        if not pixmap.isNull():
            pixmap = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.logo_label.setPixmap(pixmap)
            self.logo_label.setAlignment(Qt.AlignCenter)
            self.main_layout.addWidget(self.logo_label)
        else:
            print("Error: Could not load logo from D:\\SERENA AI\\Kl University-01.jpg")

        self.time_label = QLabel("Time: Loading...", self)
        self.time_label.setFont(self.tesla_font)
        self.time_label.setStyleSheet("color: #FFFFFF; padding: 10px;")
        self.main_layout.addWidget(self.time_label, alignment=Qt.AlignCenter)

        self.dashboard_layout = QHBoxLayout()

        self.car_widget = QWidget()
        self.car_layout = QVBoxLayout(self.car_widget)
        self.car_layout.setAlignment(Qt.AlignCenter)

        self.speed_label = QLabel(f"🚗 Speed: {car_data['speed']:.1f} km/h", self)
        self.speed_label.setFont(self.tesla_font)
        self.speed_label.setStyleSheet("color: #00FF00; padding: 10px; background: rgba(0, 0, 0, 0.3); border-radius: 5px;")
        self.car_layout.addWidget(self.speed_label)

        self.battery_label = QLabel(f"🔋 Battery: {car_data['battery']:.1f}%", self)
        self.battery_label.setFont(self.tesla_font_small)
        self.battery_label.setStyleSheet("color: #00FFFF; padding: 10px; background: rgba(0, 0, 0, 0.3); border-radius: 5px;")
        self.car_layout.addWidget(self.battery_label)

        self.tire_label = QLabel(f"🛞 Tire Pressure: {car_data['tire_pressure']:.1f} bar", self)
        self.tire_label.setFont(self.tesla_font_small)
        self.tire_label.setStyleSheet("color: #FFFF00; padding: 10px; background: rgba(0, 0, 0, 0.3); border-radius: 5px;")
        self.car_layout.addWidget(self.tire_label)

        self.engine_label = QLabel(f"⚙ Engine Temp: {car_data['engine_temp']:.1f}°C", self)
        self.engine_label.setFont(self.tesla_font_small)
        self.engine_label.setStyleSheet("color: #FF5555; padding: 10px; background: rgba(0, 0, 0, 0.3); border-radius: 5px;")
        self.car_layout.addWidget(self.engine_label)

        self.seatbelt_label = QLabel(f"🔔 Seatbelt: {car_data['seatbelt']}", self)
        self.seatbelt_label.setFont(self.tesla_font_small)
        self.seatbelt_label.setStyleSheet("color: #FFAA00; padding: 10px; background: rgba(0, 0, 0, 0.3); border-radius: 5px;")
        self.car_layout.addWidget(self.seatbelt_label)

        self.dashboard_layout.addWidget(self.car_widget)

        self.response_widget = QWidget()
        self.response_layout = QVBoxLayout(self.response_widget)

        self.response_label = QLabel("Serena AI: Awaiting your command...", self)
        self.response_label.setFont(self.tesla_font)
        self.response_label.setStyleSheet("color: #FFFFFF; padding: 15px;")
        self.response_label.setWordWrap(True)
        self.response_layout.addWidget(self.response_label)

        self.history_text = QTextEdit(self)
        self.history_text.setReadOnly(True)
        self.history_text.setFont(self.tesla_font_small)
        self.history_text.setStyleSheet("color: #FFFFFF; background: rgba(0, 0, 0, 0.5); border: none;")
        self.history_text.setFixedHeight(150)
        self.history_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.response_layout.addWidget(self.history_text)

        self.button_layout = QHBoxLayout()
        
        self.mic_button = QPushButton("Engage Serena")
        self.mic_button.setFont(self.tesla_font_small)
        self.mic_button.setStyleSheet("background: #1E90FF; color: white; border-radius: 15px; padding: 10px;")
        self.mic_button.clicked.connect(self.on_mic_click)
        self.button_layout.addWidget(self.mic_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setFont(self.tesla_font_small)
        self.stop_button.setStyleSheet("background: #FF5555; color: white; border-radius: 15px; padding: 10px;")
        self.stop_button.clicked.connect(self.on_stop_click)
        self.button_layout.addWidget(self.stop_button)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setFont(self.tesla_font_small)
        self.reset_button.setStyleSheet("background: #555555; color: white; border-radius: 15px; padding: 10px;")
        self.reset_button.clicked.connect(self.on_reset_click)
        self.button_layout.addWidget(self.reset_button)

        self.theme_button = QPushButton("Theme")
        self.theme_button.setFont(self.tesla_font_small)
        self.theme_button.setStyleSheet("background: #555555; color: white; border-radius: 15px; padding: 10px;")
        self.theme_button.clicked.connect(self.toggle_theme)
        self.button_layout.addWidget(self.theme_button)

        self.hindi_button = QPushButton("Hindi")
        self.hindi_button.setFont(self.tesla_font_small)
        self.hindi_button.setStyleSheet("background: #FFAA00; color: white; border-radius: 15px; padding: 10px;")
        self.hindi_button.clicked.connect(lambda: self.set_language("hi"))
        self.button_layout.addWidget(self.hindi_button)

        self.telugu_button = QPushButton("Telugu")
        self.telugu_button.setFont(self.tesla_font_small)
        self.telugu_button.setStyleSheet("background: #00FFAA; color: white; border-radius: 15px; padding: 10px;")
        self.telugu_button.clicked.connect(lambda: self.set_language("te"))
        self.button_layout.addWidget(self.telugu_button)

        self.other_lang_combo = QComboBox()
        self.other_lang_combo.addItems([GTTS_LANGUAGES[lang] for lang in GTTS_LANGUAGES])
        self.other_lang_combo.setFont(self.tesla_font_small)
        self.other_lang_combo.setStyleSheet("background: #AA00FF; color: white; border-radius: 15px; padding: 10px;")
        self.other_lang_combo.currentTextChanged.connect(self.set_other_language)
        self.button_layout.addWidget(self.other_lang_combo)

        self.response_layout.addLayout(self.button_layout)
        self.dashboard_layout.addWidget(self.response_widget)
        self.main_layout.addLayout(self.dashboard_layout)

        self.update_theme()
        self.data_timer = QTimer(self)
        self.data_timer.timeout.connect(self.update_time_and_data)
        self.data_timer.start(3000)

        self.response_label.setText("Serena AI: Welcome aboard! Click 'Engage Serena' to talk.")
        self.append_history("Serena AI started.")
        self.speak("Welcome aboard! I’m Serena, your co-pilot at KL University. Click Engage Serena to talk.", "en")

    def speak(self, text, lang="en"):
        if not speaking:
            audio_thread = AudioThread(text, lang)
            audio_thread.finished.connect(lambda: self.audio_threads.remove(audio_thread) if audio_thread in self.audio_threads else None)
            self.audio_threads.append(audio_thread)
            audio_thread.start()

    def set_language(self, lang):
        global response_lang
        response_lang = lang
        lang_name = GTTS_LANGUAGES[lang]
        self.response_label.setText(f"Serena AI: Switched to {lang_name}.")
        if lang == "hi":
            self.speak("ہندی میں جواب دینے کے لئے تیار۔", "hi")
        elif lang == "te":
            self.speak("తెలుగులో సమాధానం ఇవ్వడానికి సిద్ధం.", "te")
        else:
            self.speak(f"Switched to {lang_name}.", lang)
        self.append_history(f"Switched to {lang_name}")

    def set_other_language(self, lang_name):
        global response_lang
        for code, name in GTTS_LANGUAGES.items():
            if name == lang_name:
                response_lang = code
                break
        self.response_label.setText(f"Serena AI: Switched to {lang_name}.")
        if response_lang == "hi":
            self.speak("ہندی میں جواب دینے کے لئے تیار۔", "hi")
        elif response_lang == "te":
            self.speak("తెలుగులో సమాధానం ఇవ్వడానికి సిద్ధం.", "te")
        else:
            self.speak(f"Switched to {lang_name}.", response_lang)
        self.append_history(f"Switched to {lang_name}")

    def update_theme(self):
        palette = self.palette()
        if self.is_day_mode:
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0.0, QColor(50, 50, 50))
            gradient.setColorAt(1.0, QColor(20, 20, 20))
        else:
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0.0, QColor(10, 10, 30))
            gradient.setColorAt(1.0, QColor(5, 5, 15))
        palette.setBrush(QPalette.Window, QBrush(gradient))
        self.setPalette(palette)
        self.theme_button.setEnabled(not busy)

    def toggle_theme(self):
        global busy, response_lang
        if not busy:
            self.is_day_mode = not self.is_day_mode
            self.update_theme()
            mode = "Day" if self.is_day_mode else "Night"
            self.response_label.setText(f"Serena AI: {mode} mode activated.")
            if response_lang == "hi":
                self.speak(f"{mode} موڈ فعال ہو گیا۔", "hi")
            elif response_lang == "te":
                self.speak(f"{mode} మోడ్ యాక్టివేట్ చేయబడింది.", "te")
            else:
                self.speak(f"{mode} mode activated.", response_lang)
            self.append_history(f"Theme set to {mode}")

    def update_time_and_data(self):
        india_tz = pytz.timezone("Asia/Kolkata")
        current_time = datetime.now(india_tz).strftime("%H:%M:%S - %B %d, %Y")
        self.time_label.setText(f"Time in India: {current_time}")
        simulate_car_data()
        if "speed" not in self.last_update or abs(self.last_update["speed"] - car_data["speed"]) > 0.1:
            self.speed_label.setText(f"🚗 Speed: {car_data['speed']:.1f} km/h")
            self.last_update["speed"] = car_data["speed"]
        if "battery" not in self.last_update or abs(self.last_update["battery"] - car_data["battery"]) > 0.1:
            self.battery_label.setText(f"🔋 Battery: {car_data['battery']:.1f}%")
            self.last_update["battery"] = car_data["battery"]
        if "tire_pressure" not in self.last_update or abs(self.last_update["tire_pressure"] - car_data["tire_pressure"]) > 0.01:
            self.tire_label.setText(f"🛞 Tire Pressure: {car_data['tire_pressure']:.1f} bar")
            self.last_update["tire_pressure"] = car_data["tire_pressure"]
        if "engine_temp" not in self.last_update or abs(self.last_update["engine_temp"] - car_data["engine_temp"]) > 0.5:
            self.engine_label.setText(f"⚙ Engine Temp: {car_data['engine_temp']:.1f}°C")
            self.last_update["engine_temp"] = car_data["engine_temp"]
        if "seatbelt" not in self.last_update or self.last_update["seatbelt"] != car_data["seatbelt"]:
            self.seatbelt_label.setText(f"🔔 Seatbelt: {car_data['seatbelt']}")
            self.last_update["seatbelt"] = car_data["seatbelt"]

    def append_history(self, text):
        self.history_text.append(f"{datetime.now().strftime('%H:%M:%S')}: {text}")
        scrollbar = self.history_text.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum() - 20:
            scrollbar.setValue(scrollbar.maximum())

    def on_mic_click(self):
        global busy
        if not busy:
            busy = True
            self.response_label.setText("Serena AI: Listening...")
            self.manual_speech_thread = ManualSpeechThread()
            self.manual_speech_thread.command_signal.connect(self.process_command)
            self.manual_speech_thread.error_signal.connect(self.handle_error)
            self.manual_speech_thread.finished.connect(lambda: setattr(self, 'busy', False))
            self.manual_speech_thread.start()
        else:
            self.response_label.setText("Serena AI: Please wait, I’m processing...")

    def get_weather_async(self, city):
        with ThreadPoolExecutor() as executor:
            future = executor.submit(get_weather, city)
            return future.result()

    def call_genai_api_async(self, command):
        with ThreadPoolExecutor() as executor:
            future = executor.submit(call_genai_api, command)
            return future.result()

    def process_command(self, command, detected_lang):
        global busy, response_lang
        self.response_label.setText(f"You said: {command} (Detected: {detected_lang})")
        self.append_history(f"You said: {command} (Detected: {detected_lang})")
        busy = True

        try:
            if "tell in hindi" in command or "हिंदी में बताओ" in command:
                self.set_language("hi")
            elif "tell in telugu" in command or "తెలుగులో చెప్పు" in command:
                self.set_language("te")
            elif "tell in urdu" in command or "اردو میں بتائیں" in command:
                self.set_language("ur")
            elif "weather" in command or "मौसम" in command or "వాతావరణం" in command or "موسم" in command:
                city = command.split("in")[-1].strip() if "in" in command else "London"
                weather_info = self.get_weather_async(city)
                if response_lang == "hi":
                    lines = weather_info.split("\n")
                    translated = (
                        f"📍 {lines[0].split('📍 ')[1]}\n"
                        f"🌎 अक्षांश: {lines[1].split('Latitude: ')[1].split(',')[0]}, देशांतर: {lines[1].split('Longitude: ')[1]}\n"
                        f"🌡 तापमान: {lines[2].split('Temperature: ')[1].split(' (')[0]} (ऐसा लगता है {lines[2].split('Feels like ')[1].split(')')[0]})\n"
                        f"💨 हवा: {lines[3].split('Wind: ')[1].split(' (')[0]} ({lines[3].split('(')[1].split(')')[0]})\n"
                        f"☁ बादल: {lines[4].split('Cloud Cover: ')[1]}\n"
                        f"💧 नमी: {lines[5].split('Humidity: ')[1]}\n"
                        f"👁 दृश्यता: {lines[6].split('Visibility: ')[1]}\n"
                        f"📊 दबाव: {lines[7].split('Pressure: ')[1]}\n"
                        f"🌅 सूर्योदय: {lines[8].split('Sunrise: ')[1]}\n"
                        f"🌇 सूर्यास्त: {lines[9].split('Sunset: ')[1]}\n"
                        f"🌤 स्थिति: {lines[10].split('Condition: ')[1]}"
                    )
                    self.response_label.setText(f"Serena AI:\n{translated}")
                    self.speak(translated, "hi")
                elif response_lang == "te":
                    lines = weather_info.split("\n")
                    translated = (
                        f"📍 {lines[0].split('📍 ')[1]}\n"
                        f"🌎 అక్షాంశం: {lines[1].split('Latitude: ')[1].split(',')[0]}, రేఖాంశం: {lines[1].split('Longitude: ')[1]}\n"
                        f"🌡 ఉష్ణోగ్రత: {lines[2].split('Temperature: ')[1].split(' (')[0]} (అనుభూతి {lines[2].split('Feels like ')[1].split(')')[0]})\n"
                        f"💨 గాలి: {lines[3].split('Wind: ')[1].split(' (')[0]} ({lines[3].split('(')[1].split(')')[0]})\n"
                        f"☁ మేఘాలు: {lines[4].split('Cloud Cover: ')[1]}\n"
                        f"💧 ఆర్ద్రత: {lines[5].split('Humidity: ')[1]}\n"
                        f"👁 దృశ్యమానత: {lines[6].split('Visibility: ')[1]}\n"
                        f"📊 ఒత్తిడి: {lines[7].split('Pressure: ')[1]}\n"
                        f"🌅 సూర్యోదయం: {lines[8].split('Sunrise: ')[1]}\n"
                        f"🌇 సూర్యాస్తమయం: {lines[9].split('Sunset: ')[1]}\n"
                        f"🌤 పరిస్థితి: {lines[10].split('Condition: ')[1]}"
                    )
                    self.response_label.setText(f"Serena AI:\n{translated}")
                    self.speak(translated, "te")
                elif response_lang == "ur":
                    lines = weather_info.split("\n")
                    translated = (
                        f"📍 {lines[0].split('📍 ')[1]}\n"
                        f"🌎 عرض البلد: {lines[1].split('Latitude: ')[1].split(',')[0]}, طول البلد: {lines[1].split('Longitude: ')[1]}\n"
                        f"🌡 درجہ حرارت: {lines[2].split('Temperature: ')[1].split(' (')[0]} (محسوس ہوتا ہے {lines[2].split('Feels like ')[1].split(')')[0]})\n"
                        f"💨 ہوا: {lines[3].split('Wind: ')[1].split(' (')[0]} ({lines[3].split('(')[1].split(')')[0]})\n"
                        f"☁ بادل: {lines[4].split('Cloud Cover: ')[1]}\n"
                        f"💧 نمی: {lines[5].split('Humidity: ')[1]}\n"
                        f"👁 مرئیت: {lines[6].split('Visibility: ')[1]}\n"
                        f"📊 دباؤ: {lines[7].split('Pressure: ')[1]}\n"
                        f"🌅 طلوع آفتاب: {lines[8].split('Sunrise: ')[1]}\n"
                        f"🌇 غروب آفتاب: {lines[9].split('Sunset: ')[1]}\n"
                        f"🌤 حالت: {lines[10].split('Condition: ')[1]}"
                    )
                    self.response_label.setText(f"Serena AI:\n{translated}")
                    self.speak(translated, "ur")
                else:
                    self.response_label.setText(f"Serena AI:\n{weather_info}")
                    self.speak(weather_info, response_lang)
                self.append_history(weather_info)
            elif "speed" in command or "گति" in command or "వేగం" in command or "رفتار" in command:
                response_en = f"Speed is {car_data['speed']:.1f} kilometers per hour."
                if response_lang == "hi":
                    response = f"گति {car_data['speed']:.1f} کلومیٹر فی گھنٹہ ہے۔"
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "hi")
                elif response_lang == "te":
                    response = f"వేగం {car_data['speed']:.1f} కిలోమీటర్లు గంటకు."
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "te")
                elif response_lang == "ur":
                    response = f"رفتار {car_data['speed']:.1f} کلومیٹر فی گھنٹہ ہے۔"
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "ur")
                else:
                    self.response_label.setText(f"Serena AI: {response_en}")
                    self.speak(response_en, response_lang)
                self.append_history(response_en)
            elif "battery" in command or "बैटरी" in command or "బ్యాటరీ" in command or "بیٹری" in command:
                response_en = f"Battery at {car_data['battery']:.1f} percent."
                if response_lang == "hi":
                    response = f"بیٹری {car_data['battery']:.1f} فیصد پر ہے۔"
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "hi")
                elif response_lang == "te":
                    response = f"బ్యాటరీ {car_data['battery']:.1f} శాతం వద్ద ఉంది."
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "te")
                elif response_lang == "ur":
                    response = f"بیٹری {car_data['battery']:.1f} فیصد پر ہے۔"
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "ur")
                else:
                    self.response_label.setText(f"Serena AI: {response_en}")
                    self.speak(response_en, response_lang)
                self.append_history(response_en)
            elif "time" in command or "समय" in command or "సమయం" in command or "وقت" in command:
                india_tz = pytz.timezone("Asia/Kolkata")
                current_time = datetime.now(india_tz).strftime("%H:%M:%S on %B %d, %Y")
                if response_lang == "hi":
                    response = f"समय {current_time} ہے۔"
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "hi")
                elif response_lang == "te":
                    response = f"సమయం {current_time}."
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "te")
                elif response_lang == "ur":
                    response = f"وقت {current_time} ہے۔"
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "ur")
                else:
                    self.response_label.setText(f"Serena AI: {current_time}")
                    self.speak(f"The time is {current_time}", response_lang)
                self.append_history(current_time)
            elif "calculate" in command or "गणना" in command or "లెక్కించు" in command or "حساب" in command or any(c in command for c in '+-*/=x'):
                response_en = calculate_math(command)
                if response_lang == "hi":
                    result = response_en.split("is ")[-1]
                    response = f"نتیجہ {result} ہے۔"
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "hi")
                elif response_lang == "te":
                    result = response_en.split("is ")[-1]
                    response = f"ఫలితం {result}."
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "te")
                elif response_lang == "ur":
                    result = response_en.split("is ")[-1]
                    response = f"نتیجہ {result} ہے۔"
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "ur")
                else:
                    self.response_label.setText(f"Serena AI: {response_en}")
                    self.speak(response_en, response_lang)
                self.append_history(response_en)
            elif "exit" in command or "बाहर निकलें" in command or "విడిచిపెట్టు" in command or "باہر نکلیں" in command:
                if response_lang == "hi":
                    self.response_label.setText("Serena AI: الوداع۔")
                    self.speak("الوداع۔", "hi")
                elif response_lang == "te":
                    self.response_label.setText("Serena AI: వీడ్కోలు.")
                    self.speak("వీడ్కోలు.", "te")
                elif response_lang == "ur":
                    self.response_label.setText("Serena AI: الوداع۔")
                    self.speak("الوداع۔", "ur")
                else:
                    self.response_label.setText("Serena AI: Goodbye.")
                    self.speak("Goodbye.", response_lang)
                self.append_history("Shutting down.")
                self.close()
            else:
                response_en = self.call_genai_api_async(command)
                if response_lang == "hi":
                    response = self.call_genai_api_async(f"Translate to Hindi: {response_en}")
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "hi")
                elif response_lang == "te":
                    response = self.call_genai_api_async(f"Translate to Telugu: {response_en}")
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "te")
                elif response_lang == "ur":
                    response = self.call_genai_api_async(f"Translate to Urdu: {response_en}")
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, "ur")
                elif response_lang != "en":
                    response = self.call_genai_api_async(f"Translate to {GTTS_LANGUAGES[response_lang]}: {response_en}")
                    self.response_label.setText(f"Serena AI: {response}")
                    self.speak(response, response_lang)
                else:
                    self.response_label.setText(f"Serena AI: {response_en}")
                    self.speak(response_en, response_lang)
                self.append_history(response_en)
        except Exception as e:
            error_en = f"Sorry, something went wrong: {str(e)}"
            if response_lang == "hi":
                self.response_label.setText(f"Serena AI: معاف کریں، کچھ غلط ہو گیا: {str(e)}")
                self.speak(f"معاف کریں، کچھ غلط ہو گیا: {str(e)}", "hi")
            elif response_lang == "te":
                self.response_label.setText(f"Serena AI: క్షమించండి, ఏదో తప్పు జరిగింది: {str(e)}")
                self.speak(f"క్షమించండి, ఏదో తప్పు జరిగింది: {str(e)}", "te")
            elif response_lang == "ur":
                self.response_label.setText(f"Serena AI: معاف کریں، کچھ غلط ہو گیا: {str(e)}")
                self.speak(f"معاف کریں، کچھ غلط ہو گیا: {str(e)}", "ur")
            else:
                self.response_label.setText(f"Serena AI: {error_en}")
                self.speak(error_en, response_lang)
            self.append_history(error_en)
        busy = False

    def handle_error(self, error):
        global busy, response_lang
        self.response_label.setText(f"Serena AI: {error}")
        if response_lang == "hi":
            self.speak("معاف کریں، میں سمجھ نہیں سکی۔", "hi")
        elif response_lang == "te":
            self.speak("క్షమించండి, నాకు అర్థం కాలేదు.", "te")
        elif response_lang == "ur":
            self.speak("معاف کریں، میں سمجھ نہیں سکی۔", "ur")
        else:
            self.speak(error, response_lang)
        self.append_history(error)
        busy = False

    def on_stop_click(self):
        global speaking
        if speaking:
            if pygame.mixer.get_busy():
                pygame.mixer.stop()
            else:
                engine.stop()
            speaking = False
        self.response_label.setText("Serena AI: Speech stopped.")

    def on_reset_click(self):
        global car_data
        car_data = initial_car_data.copy()
        self.history_text.clear()
        self.response_label.setText("Serena AI: Data reset.")
        if response_lang == "hi":
            self.speak("डेटا ر سیٹ کر دیا گیا۔", "hi")
        elif response_lang == "te":
            self.speak("డేటా రీసెట్ చేయబడింది.", "te")
        elif response_lang == "ur":
            self.speak("ڈیٹا ری سیٹ کر دیا گیا۔", "ur")
        else:
            self.speak("Data reset.", response_lang)
        self.append_history("Data reset.")
        self.update_time_and_data()

    def closeEvent(self, event):
        for thread in self.audio_threads:
            if thread.isRunning():
                thread.wait()
        event.accept()

if _name_ == "_main_":
    app = QApplication(sys.argv)
    window = SerenaAIWindow()
    window.show()
    sys.exit(app.exec_())
