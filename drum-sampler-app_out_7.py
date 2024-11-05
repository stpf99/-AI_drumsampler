import gi
import random
import time
import threading
import pygame
import json
import os
from midiutil import MIDIFile
import statistics
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range, low_pass_filter, high_pass_filter
import io
import numpy as np
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk
import warnings
warnings.filterwarnings("ignore", category=SyntaxWarning)
import sqlite3
import requests

class DrumSamplerApp(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Drum Sampler")
        self.set_border_width(10)
        self.ai_composer = AIComposer()
        self.setup_database()
        pygame.mixer.init()

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(self.main_box)

        # Bazowy BPM oraz struktury do przechowywania gęstości patternów
        self.base_bpm = 80
        self.absolute_bpm = 120  # Domyślny BPM
        self.genre_bpm = {"House": 125, "Techno": 130, "Drum and Bass": 165, "Ambient": 80}  # Przykładowe wartości
        self.instruments = ['Talerz', 'Stopa', 'Werbel', 'TomTom']
        self.patterns = {inst: [0] * 16 for inst in self.instruments}

        # Create toolbar
        self.create_toolbar()

        self.grid = Gtk.Grid()
        self.main_box.pack_start(self.grid, True, True, 0)

        self.instruments = ['Talerz', 'Stopa', 'Werbel', 'TomTom']
        self.colors = ['red', 'green', 'blue', 'orange']
        self.patterns = {inst: [0] * 16 for inst in self.instruments}
        self.samples = {}
        self.buttons = {}
        # Inside the __init__ method of DrumSamplerApp
        self.effects = {inst: {'volume': 0, 'pitch': 0, 'echo': 0, 'reverb': 0, 'distortion': 0, 'pan': 0} for inst in self.instruments}


        # MIDI note mapping for instruments
        self.midi_notes = {'Talerz': 49, 'Stopa': 36, 'Werbel': 38, 'TomTom': 45}

        # Add numbers from 1 to 16 above the pattern
        for step in range(16):
            label = Gtk.Label(label=str(step + 1))
            self.grid.attach(label, step + 1, 0, 1, 1)

        for idx, (instrument, color) in enumerate(zip(self.instruments, self.colors)):
            label = Gtk.Label(label=instrument)
            self.grid.attach(label, 0, idx + 1, 1, 1)

            self.buttons[instrument] = []
            for step in range(16):
                button = Gtk.ToggleButton()
                button.set_size_request(30, 30)
                context = button.get_style_context()
                context.add_class(f"circle-{color}")
                button.connect("toggled", self.on_button_toggled, instrument, step)
                self.grid.attach(button, step + 1, idx + 1, 1, 1)
                self.buttons[instrument].append(button)

        self.loop_playing = False
        self.play_thread = None
        self.absolute_bpm = 120  # Default absolute BPM
        self.dynamic_bpm_list = []
        self.current_bpm_index = 0
        self.steps_per_bpm = 4  # Liczba kroków przed zmianą BPM

        # Add CSS for circular buttons
        self.add_css()

        # Add controls
        self.create_pattern_controls()
        self.create_bpm_controls()
        self.create_matched_bpm_control()
        self.create_pattern_controls()
        self.create_pattern_length_control()
        self.create_instrument_randomization_controls()
        self.create_dynamic_bpm_control()
        self.create_preset_selection()
        self.create_effect_controls()


    def add_css(self):
        css_provider = Gtk.CssProvider()
        css = """
        .circle-red, .circle-green, .circle-blue, .circle-orange {
            border-radius: 15px;
            background-color: white;
        }
        .circle-red:checked { background-color: red; }
        .circle-green:checked { background-color: green; }
        .circle-blue:checked { background-color: blue; }
        .circle-orange:checked { background-color: orange; }
        @keyframes blink-animation {
            0% { opacity: 1; }
            50% { opacity: 0; }
            100% { opacity: 1; }
        }
        .blink {
            animation: blink-animation 0.5s linear 2;
        }
        """
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


    def create_pattern_controls(self):
        genre_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(genre_box, False, False, 0)

        genre_label = Gtk.Label(label="Select Genre:")
        genre_box.pack_start(genre_label, False, False, 0)

        self.genre_entry = Gtk.ComboBoxText()
        genres = ["House", "Techno", "Drum and Bass", "Ambient"]
        for genre in genres:
            self.genre_entry.append_text(genre)
        self.genre_entry.set_active(0)
        genre_box.pack_start(self.genre_entry, False, False, 0)


    def setup_database(self):
        self.conn = sqlite3.connect("pattern_genres_logic.db")
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS patterns (
                genre TEXT PRIMARY KEY,
                logic TEXT
            )
        ''')
        self.conn.commit()

    def on_button_toggled(self, button, instrument, step):
        self.patterns[instrument][step] = int(button.get_active())

    def create_preset_selection(self):
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(preset_box, False, False, 0)

        preset_label = Gtk.Label(label="Techno Preset:")
        preset_box.pack_start(preset_label, False, False, 0)

        self.preset_combo = Gtk.ComboBoxText()
        self.preset_combo.append_text("None")
        self.preset_combo.append_text("Basic Techno")
        self.preset_combo.append_text("Minimal Techno")
        self.preset_combo.append_text("Hard Techno")
        self.preset_combo.set_active(0)
        preset_box.pack_start(self.preset_combo, False, False, 0)

        apply_preset_button = Gtk.Button(label="Apply Preset")
        apply_preset_button.connect("clicked", self.apply_preset)
        preset_box.pack_start(apply_preset_button, False, False, 0)

    def apply_preset(self, widget):
        preset = self.preset_combo.get_active_text()
        if preset == "Basic Techno":
            self.generate_basic_techno()
        elif preset == "Minimal Techno":
            self.generate_minimal_techno()
        elif preset == "Hard Techno":
            self.generate_hard_techno()
        self.update_buttons()

    def apply_preset(self, widget):
        preset = self.preset_combo.get_active_text()
        if preset == "Basic Techno":
            self.generate_basic_techno()
        elif preset == "Minimal Techno":
            self.generate_minimal_techno()
        elif preset == "Hard Techno":
            self.generate_hard_techno()
        self.update_buttons()

    def generate_basic_techno(self):
        pattern_length = int(self.length_spinbutton.get_value())
        for i in range(pattern_length):
            self.patterns['Stopa'][i] = 1 if i % 4 == 0 else 0
            self.patterns['Werbel'][i] = 1 if i % 8 == 4 else 0
            self.patterns['Talerz'][i] = 1 if i % 4 == 2 else 0
            self.patterns['TomTom'][i] = 1 if i % 16 == 14 else 0

    def generate_minimal_techno(self):
        pattern_length = int(self.length_spinbutton.get_value())
        for i in range(pattern_length):
            self.patterns['Stopa'][i] = 1 if i % 4 == 0 or i % 16 == 14 else 0
            self.patterns['Werbel'][i] = 1 if i % 8 == 4 else 0
            self.patterns['Talerz'][i] = 1 if i % 2 == 0 else 0
            self.patterns['TomTom'][i] = 1 if i % 16 == 10 else 0

    def generate_hard_techno(self):
        pattern_length = int(self.length_spinbutton.get_value())
        for i in range(pattern_length):
            self.patterns['Stopa'][i] = 1 if i % 2 == 0 else 0
            self.patterns['Werbel'][i] = 1 if i % 8 == 4 or i % 8 == 6 else 0
            self.patterns['Talerz'][i] = 1 if i % 4 == 0 else 0
            self.patterns['TomTom'][i] = 1 if i % 8 == 7 else 0

    def update_buttons(self):
        pattern_length = int(self.length_spinbutton.get_value())
        for inst in self.instruments:
            for i in range(pattern_length):
                self.buttons[inst][i].set_active(bool(self.patterns[inst][i]))

    def create_toolbar(self):
        toolbar = Gtk.Toolbar()
        self.main_box.pack_start(toolbar, False, False, 0)

        button_info = [
            ("media-playback-start", self.play_pattern, "Play"),
            ("media-playback-stop", self.stop_pattern, "Stop"),
            ("view-refresh", self.randomize_pattern, "Randomize"),
            ("document-open", self.load_samples, "Load Samples"),
            ("document-save", self.save_project, "Save Project"),
            ("document-open", self.load_project, "Load Project"),
            ("document-export", self.export_to_midi, "Export MIDI"),
            ("document-export", self.export_advanced_midi, "Export Advanced MIDI")  # New button
        ]

        for icon_name, callback, tooltip in button_info:
            button = Gtk.ToolButton()
            button.set_icon_name(icon_name)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", callback)
            toolbar.insert(button, -1)



        # Create audio backend selection dropdown
        audio_backend_label = Gtk.Label(label="Audio Backend:")
        toolbar.insert(Gtk.ToolItem(), -1)  # Spacer
        audio_backend_item = Gtk.ToolItem()
        backend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        self.backend_combo = Gtk.ComboBoxText()
        self.backend_combo.append_text("PipeWire")
        self.backend_combo.append_text("JACK")
        self.backend_combo.set_active(0)  # Default to PipeWire

        backend_box.pack_start(audio_backend_label, False, False, 0)
        backend_box.pack_start(self.backend_combo, False, False, 0)
        audio_backend_item.add(backend_box)
        toolbar.insert(audio_backend_item, -1)
        toolbar.show_all()

    def create_bpm_controls(self):
        bpm_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(bpm_box, False, False, 0)

        bpm_label = Gtk.Label(label="Absolute BPM:")
        bpm_box.pack_start(bpm_label, False, False, 0)

        self.bpm_entry = Gtk.Entry()
        self.bpm_entry.set_text(str(self.absolute_bpm))
        self.bpm_entry.set_width_chars(4)
        bpm_box.pack_start(self.bpm_entry, False, False, 0)

        bpm_up_button = Gtk.Button()
        bpm_up_button.set_image(Gtk.Image.new_from_icon_name("go-up", Gtk.IconSize.SMALL_TOOLBAR))
        bpm_up_button.set_tooltip_text("Increase BPM")
        bpm_up_button.connect("clicked", self.bpm_step_up)
        bpm_box.pack_start(bpm_up_button, False, False, 0)

        bpm_down_button = Gtk.Button()
        bpm_down_button.set_image(Gtk.Image.new_from_icon_name("go-down", Gtk.IconSize.SMALL_TOOLBAR))
        bpm_down_button.set_tooltip_text("Decrease BPM")
        bpm_down_button.connect("clicked", self.bpm_step_down)
        bpm_box.pack_start(bpm_down_button, False, False, 0)


    def calculate_pattern_density(self):
        """Oblicza zagęszczenie patternu jako średnią aktywnych kroków dla każdego instrumentu."""
        total_active_steps = sum(sum(steps) for steps in self.patterns.values())
        total_steps = sum(len(steps) for steps in self.patterns.values())
        return total_active_steps / total_steps if total_steps > 0 else 0

    def matched_bpm(self, widget):
        """Dostosowuje BPM na podstawie zagęszczenia patternu w stosunku do bazowego BPM."""
        density = self.calculate_pattern_density()
        new_bpm = self.base_bpm + (density - 0.5) * 80  # Skaluje BPM na podstawie zagęszczenia
        self.absolute_bpm = int(new_bpm)
        self.bpm_entry.set_text(str(self.absolute_bpm))
        print(f"Matched BPM ustawiony na: {self.absolute_bpm}")

    def perfect_tempo_bpm(self, widget):
        """Dostosowuje BPM do średniego tempa gatunku, po wcześniejszym wywołaniu funkcji matched_bpm."""
        self.matched_bpm(widget)  # Uruchomienie najpierw matched BPM
        genre = self.genre_entry.get_active_text()
        avg_bpm = self.genre_bpm.get(genre, self.base_bpm)
        self.absolute_bpm = int((self.absolute_bpm + avg_bpm) / 2)  # Średnia BPM po matched BPM
        self.bpm_entry.set_text(str(self.absolute_bpm))
        print(f"Perfect Tempo BPM ustawiony na: {self.absolute_bpm}")


    def create_matched_bpm_control(self):
        """Tworzy przyciski do ustawiania BPM na podstawie zagęszczenia patternu."""
        bpm_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(bpm_box, False, False, 0)

        matched_bpm_button = Gtk.Button(label="Matched BPM")
        matched_bpm_button.connect("clicked", self.matched_bpm)
        bpm_box.pack_start(matched_bpm_button, False, False, 0)

        perfect_bpm_button = Gtk.Button(label="Perfect Tempo BPM")
        perfect_bpm_button.connect("clicked", self.perfect_tempo_bpm)
        bpm_box.pack_start(perfect_bpm_button, False, False, 0)

    def on_absolute_bpm_changed(self, widget):
        try:
            self.absolute_bpm = int(self.bpm_entry.get_text())
            self.update_dynamic_bpm()
        except ValueError:
            print("Invalid BPM input. Please enter an integer.")

    def bpm_step_up(self, widget):
        self.absolute_bpm = min(300, self.absolute_bpm + 5)  # Limit maximum BPM to 300
        self.bpm_entry.set_text(str(self.absolute_bpm))
        self.update_dynamic_bpm()

    def bpm_step_down(self, widget):
        self.absolute_bpm = max(60, self.absolute_bpm - 5)  # Limit minimum BPM to 60
        self.bpm_entry.set_text(str(self.absolute_bpm))
        self.update_dynamic_bpm()

    def randomize_pattern(self, widget):
        pattern_length = int(self.length_spinbutton.get_value())
        for inst in self.instruments:
            for i in range(pattern_length):
                if inst == 'Stopa':
                    self.patterns[inst][i] = random.choice([1, 0]) if i % 4 == 0 else 0
                elif inst == 'Werbel':
                    self.patterns[inst][i] = 1 if i % 4 == 2 else 0
                elif inst == 'Talerz':
                    self.patterns[inst][i] = random.choice([0, 1]) if self.patterns['Stopa'][i] == 0 else 0
                elif inst == 'TomTom':
                    self.patterns[inst][i] = random.choice([0, 1]) if i % 8 == 7 else 0

        # Call instrument randomization after generating the base pattern
        self.randomize_instruments(None)

    def load_samples(self, widget):
        for inst in self.instruments:
            file_dialog = Gtk.FileChooserDialog(
                title="Wybierz sample dla " + inst,
                action=Gtk.FileChooserAction.OPEN,
                buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

            response = file_dialog.run()
            if response == Gtk.ResponseType.OK:
                filename = file_dialog.get_filename()
                self.samples[inst] = filename
                print(f"Wczytano sample {inst}: {filename}")
            file_dialog.destroy()

    def create_instrument_randomization_controls(self):
        randomize_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(randomize_box, False, False, 0)

        randomize_label = Gtk.Label(label="Instrument Randomization:")
        randomize_box.pack_start(randomize_label, False, False, 0)

        self.randomize_probability_adjustment = Gtk.Adjustment(value=10, lower=0, upper=100, step_increment=1)
        self.randomize_probability_spin = Gtk.SpinButton()
        self.randomize_probability_spin.set_adjustment(self.randomize_probability_adjustment)
        self.randomize_probability_spin.set_value(10)
        randomize_box.pack_start(self.randomize_probability_spin, False, False, 0)

        randomize_button = Gtk.Button(label="Randomize Instruments")
        randomize_button.connect("clicked", self.randomize_instruments)
        randomize_box.pack_start(randomize_button, False, False, 0)

    def randomize_instruments(self, widget):
        probability = self.randomize_probability_spin.get_value() / 100
        pattern_length = int(self.length_spinbutton.get_value())

        for step in range(pattern_length):
            if random.random() < probability:
                # Choose two random instruments to swap
                inst1, inst2 = random.sample(self.instruments, 2)

                # Swap the instruments for this step
                self.patterns[inst1][step], self.patterns[inst2][step] = self.patterns[inst2][step], self.patterns[inst1][step]

        self.update_buttons()

    def init_audio(self):
        # Get the selected backend
        selected_backend = self.backend_combo.get_active_text()

        if selected_backend == "PipeWire":
            # Default SDL setup for PipeWire
            pygame.mixer.quit()
            pygame.mixer.init()
            print("Initialized audio with PipeWire")
        elif selected_backend == "JACK":
            # Explicitly set JACK as the audio driver for SDL
            os.environ['SDL_AUDIODRIVER'] = 'jack'
            pygame.mixer.quit()
            pygame.mixer.init()
            print("Initialized audio with JACK")

    def play_pattern(self, widget):
        self.init_audio()  # Reinitialize audio with the selected backend

        if not self.loop_playing:
            self.loop_playing = True
            self.play_thread = threading.Thread(target=self.loop_play)
            self.play_thread.start()

    def blink_button(self, instrument, step):
        button = self.buttons[instrument][step]
        context = button.get_style_context()
        context.add_class("blink")
        GLib.timeout_add(500, lambda: context.remove_class("blink"))

    def stop_pattern(self, widget):
        self.loop_playing = False
        if self.play_thread is not None:
            self.play_thread.join()

    def load_project(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Wczytaj Projekt",
            action=Gtk.FileChooserAction.OPEN,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        )
        dialog.set_current_name("projekt.drsmp")
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()

            with open(filename, 'r') as f:
                project_data = json.load(f)

            self.patterns = project_data["patterns"]
            self.samples = project_data["samples"]
            bpm_entry = project_data.get("absolute_bpm", 120)  # Default to 120 if not found
            dynamic_bpm_list = project_data.get("dynamic_bpm_list", 120)  # Default to 120 if not found
            self.bpm_entry.set_text(str(self.absolute_bpm))
            self.dynamic_bpm_entry.set_text(str(self.dynamic_bpm_list))
            self.update_buttons()
            print(f"Projekt wczytany z: {filename}")

        dialog.destroy()

    def create_pattern_length_control(self):
        length_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(length_box, False, False, 0)

        length_label = Gtk.Label(label="Pattern Length:")
        length_box.pack_start(length_label, False, False, 0)

        self.length_adjustment = Gtk.Adjustment(value=16, lower=4, upper=32, step_increment=4)
        self.length_spinbutton = Gtk.SpinButton()
        self.length_spinbutton.set_adjustment(self.length_adjustment)
        self.length_spinbutton.connect("value-changed", self.on_pattern_length_changed)
        length_box.pack_start(self.length_spinbutton, False, False, 0)

    def on_pattern_length_changed(self, spinbutton):
        new_length = int(spinbutton.get_value())
        current_length = len(self.patterns[self.instruments[0]])

        for instrument in self.instruments:
            if new_length > current_length:
                self.patterns[instrument].extend([0] * (new_length - current_length))
                for i in range(current_length, new_length):
                    button = Gtk.ToggleButton()
                    button.set_size_request(30, 30)
                    context = button.get_style_context()
                    context.add_class(f"circle-{self.colors[self.instruments.index(instrument)]}")
                    button.connect("toggled", self.on_button_toggled, instrument, i)
                    self.grid.attach(button, i + 1, self.instruments.index(instrument) + 1, 1, 1)
                    self.buttons[instrument].append(button)
            elif new_length < current_length:
                self.patterns[instrument] = self.patterns[instrument][:new_length]
                for button in self.buttons[instrument][new_length:]:
                    self.grid.remove(button)
                self.buttons[instrument] = self.buttons[instrument][:new_length]

        # Update or add step labels
        for i in range(new_length):
            label = self.grid.get_child_at(i + 1, 0)
            if label is None:
                label = Gtk.Label(label=str(i + 1))
                self.grid.attach(label, i + 1, 0, 1, 1)
            else:
                label.set_visible(True)

        # Hide labels for steps beyond the new length
        for i in range(new_length, 32):
            label = self.grid.get_child_at(i + 1, 0)
            if label:
                label.set_visible(False)

        self.grid.show_all()

    def create_dynamic_bpm_control(self):
        dynamic_bpm_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(dynamic_bpm_box, False, False, 0)

        dynamic_bpm_label = Gtk.Label(label="Dynamic BPM (%):")
        dynamic_bpm_box.pack_start(dynamic_bpm_label, False, False, 0)

        self.dynamic_bpm_entry = Gtk.Entry()
        self.dynamic_bpm_entry.set_text("100,110,90,105")
        self.dynamic_bpm_entry.set_width_chars(20)
        dynamic_bpm_box.pack_start(self.dynamic_bpm_entry, False, False, 0)

        apply_button = Gtk.Button(label="Apply Dynamic BPM")
        apply_button.connect("clicked", self.apply_dynamic_bpm)
        dynamic_bpm_box.pack_start(apply_button, False, False, 0)

    def apply_dynamic_bpm(self, widget):
        bpm_string = self.dynamic_bpm_entry.get_text()
        try:
            percentages = [float(bpm.strip()) for bpm in bpm_string.split(',')]
            self.dynamic_bpm_list = [self.absolute_bpm * (p / 100) for p in percentages]
            self.current_bpm_index = 0
            print(f"Applied dynamic BPM: {self.dynamic_bpm_list}")
        except ValueError:
            print("Invalid BPM input. Please enter comma-separated numbers.")

    def update_dynamic_bpm(self):
        if self.dynamic_bpm_list:
            percentages = [float(bpm.strip()) for bpm in self.dynamic_bpm_entry.get_text().split(',')]
            self.dynamic_bpm_list = [self.absolute_bpm * (p / 100) for p in percentages]
            print(f"Updated dynamic BPM: {self.dynamic_bpm_list}")

    def get_next_bpm(self):
        if not self.dynamic_bpm_list:
            return self.absolute_bpm

        current_bpm = self.dynamic_bpm_list[self.current_bpm_index]
        return current_bpm

    def advance_bpm(self):
        if self.dynamic_bpm_list:
            self.current_bpm_index = (self.current_bpm_index + 1) % len(self.dynamic_bpm_list)

    def create_effect_controls(self):
        effect_frame = Gtk.Frame(label="Audio Effects")
        self.main_box.pack_start(effect_frame, False, False, 0)

        effect_grid = Gtk.Grid()
        effect_frame.add(effect_grid)

        instruments = ['Talerz', 'Stopa', 'Werbel', 'TomTom']
        effects = ['Volume', 'Pitch', 'Echo', 'Reverb', 'Distortion', 'Pan']

        # Add column labels
        for col, effect in enumerate(effects, start=1):
            label = Gtk.Label(label=effect)
            effect_grid.attach(label, col, 0, 1, 1)

        # Add row labels and sliders
        for row, instrument in enumerate(instruments, start=1):
            label = Gtk.Label(label=instrument)
            effect_grid.attach(label, 0, row, 1, 1)

            for col, effect in enumerate(effects, start=1):
                adjustment = Gtk.Adjustment(value=0, lower=-100, upper=100, step_increment=0.1, page_increment=1, page_size=0)
                slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
                slider.set_digits(1)  # Allow more precision
                slider.set_size_request(200, 35)  # Make the slider wider
                slider.connect('value-changed', self.on_effect_changed, instrument, effect.lower())
                effect_grid.attach(slider, col, row, 1, 1)

                # Create and attach reset button for each effect
                reset_button = Gtk.Button(label="Reset")
                reset_button.set_size_request(60, 35)  # Adjust size to fit well next to slider
                reset_button.connect('clicked', self.reset_effect, slider, instrument, effect.lower())
                effect_grid.attach(reset_button, col + len(effects), row, 1, 1)  # Place the reset button next to the slider

    def reset_effect(self, button, slider, instrument, effect):
        slider.set_value(0)  # Reset the slider to 0
        self.effects[instrument][effect] = 0
        print(f"Reset {effect} for {instrument} to 0")

    def save_project(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Zapisz Projekt",
            parent=self,
            action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK
        )
        dialog.set_current_name("projekt.drsmp")
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            project_data = {
                "patterns": self.patterns,
                "samples": self.samples,
                "absolute_bpm": self.absolute_bpm,
                "dynamic_bpm_list": self.dynamic_bpm_list
            }

            with open(filename, 'w') as f:
                json.dump(project_data, f)

            print(f"Projekt zapisany jako: {filename}")

        dialog.destroy()


    def on_effect_changed(self, slider, instrument, effect):
        value = slider.get_value()
        self.effects[instrument][effect] = value
        print(f"Changed {effect} for {instrument} to {value}")

    def apply_effects(self, sound, instrument):
        effects = self.effects[instrument]

        # Convert pygame sound to numpy array
        sound_array = pygame.sndarray.array(sound)

        # Convert numpy array to pydub AudioSegment
        sample_width = sound_array.dtype.itemsize
        audio_segment = AudioSegment(
            sound_array.tobytes(),
            frame_rate=44100,
            sample_width=sample_width,
            channels=1 if sound_array.ndim == 1 else 2
        )

        # Apply volume effect
        audio_segment = audio_segment + effects['volume']

        # Apply pitch effect
        if effects['pitch'] != 0:
            new_sample_rate = int(audio_segment.frame_rate * (2 ** (effects['pitch'] / 12)))
            audio_segment = audio_segment._spawn(audio_segment.raw_data, overrides={'frame_rate': new_sample_rate})
            audio_segment = audio_segment.set_frame_rate(44100)

        # Apply echo effect
        if effects['echo'] > 0:
            echo_sound = audio_segment.fade_out(int(len(audio_segment) * 0.5))
            audio_segment = audio_segment.overlay(echo_sound, position=int(len(audio_segment) * 0.2))

        # Apply reverb effect (simple reverb simulation)
        if effects['reverb'] > 0:
            audio_segment = audio_segment.fade_in(10).fade_out(300)

        # Apply distortion (clipping the waveform)
        if effects['distortion'] > 0:
            factor = 1 + (effects['distortion'] / 100)
            audio_segment = audio_segment.apply_gain(factor)

        # Apply pan effect
        if effects['pan'] != 0:
            audio_segment = audio_segment.pan(effects['pan'] / 100.0)

        # Convert back to numpy array
        samples = np.array(audio_segment.get_array_of_samples())

        # Ensure the array is in the correct shape for pygame
        if audio_segment.channels == 2:
            samples = samples.reshape((-1, 2))

        # Convert back to pygame Sound
        return pygame.sndarray.make_sound(samples)


    def loop_play(self):
        pattern_length = int(self.length_spinbutton.get_value())
        step_counter = 0

        while self.loop_playing:
            current_bpm = self.get_next_bpm()

            for _ in range(self.steps_per_bpm):
                if step_counter >= pattern_length:
                    step_counter = 0

                start_time = time.time()
                step_duration = 60 / current_bpm / 4

                for inst in self.instruments:
                    if self.patterns[inst][step_counter] == 1 and inst in self.samples:
                        original_sound = pygame.mixer.Sound(self.samples[inst])
                        modified_sound = self.apply_effects(original_sound, inst)
                        modified_sound.play()
                        GLib.idle_add(self.blink_button, inst, step_counter)

                elapsed_time = time.time() - start_time
                sleep_time = max(0, step_duration - elapsed_time)
                time.sleep(sleep_time)

                step_counter += 1

            self.advance_bpm()

    def export_to_midi(self, widget):
        midi = MIDIFile(1)
        track = 0
        time = 0
        midi.addTrackName(track, time, "Drum Pattern")
        midi.addTempo(track, time, self.absolute_bpm)

        pattern_length = int(self.length_spinbutton.get_value())
        for step in range(pattern_length):
            current_bpm = self.get_next_bpm()
            for inst in self.instruments:
                if self.patterns[inst][step] == 1:
                    midi.addNote(track, 9, self.midi_notes[inst], time, 0.25, 100)  # Channel 9 is for drums
            time += 60 / current_bpm / 4  # Adjust time based on current BPM

        file_dialog = Gtk.FileChooserDialog(
            title="Export MIDI",
            action=Gtk.FileChooserAction.SAVE,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
        file_dialog.set_current_name("drum_pattern.mid")

        response = file_dialog.run()
        if response == Gtk.ResponseType.OK:
            filename = file_dialog.get_filename()
            with open(filename, "wb") as output_file:
                midi.writeFile(output_file)
            print(f"MIDI file exported to: {filename}")
        file_dialog.destroy()

    def export_advanced_midi(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Export Advanced MIDI",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        )
        dialog.set_current_name("unique_track.mid")

        # Opcje stylu, BPM, dynamicznego BPM, itd.
        grid = Gtk.Grid()
        dialog.set_extra_widget(grid)

        style_label = Gtk.Label(label="Style:")
        grid.attach(style_label, 0, 0, 1, 1)
        style_combo = Gtk.ComboBoxText()
        styles = ["Techno", "House", "Drum and Bass", "Ambient"]
        for style in styles:
            style_combo.append_text(style)
        style_combo.set_active(0)
        grid.attach(style_combo, 1, 0, 1, 1)

        bpm_label = Gtk.Label(label="Target BPM:")
        grid.attach(bpm_label, 0, 1, 1, 1)
        bpm_entry = Gtk.Entry()
        bpm_entry.set_text(str(self.absolute_bpm))
        grid.attach(bpm_entry, 1, 1, 1, 1)

        dynamic_bpm_label = Gtk.Label(label="Dynamic BPM (%):")
        grid.attach(dynamic_bpm_label, 0, 2, 1, 1)
        dynamic_bpm_entry = Gtk.Entry()
        dynamic_bpm_entry.set_text(self.dynamic_bpm_entry.get_text())
        grid.attach(dynamic_bpm_entry, 1, 2, 1, 1)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            style = style_combo.get_active_text()
            target_bpm = float(bpm_entry.get_text())
            dynamic_bpm = [float(x) for x in dynamic_bpm_entry.get_text().split(',')]

            # Tworzenie pliku MIDI
            midi = MIDIFile(3)  # 3 ścieżki: drums, bass, lead

            # Dodaj nazwy ścieżek i tempo
            for i, name in enumerate(["Drums", "Bass", "Lead"]):
                midi.addTrackName(i, 0, name)
            midi.addTempo(0, 0, target_bpm)

            # Generowanie unikalnych patternów strukturalnych
            duration = 720  # 3 minuty
            structured_patterns = self.generate_structured_patterns(style, duration, target_bpm, unique=True)

            # Dodanie notatek do pliku MIDI
            self.add_structured_notes(midi, structured_patterns, dynamic_bpm)

            # Zapis pliku MIDI
            with open(filename, "wb") as output_file:
                midi.writeFile(output_file)
            print(f"Unique advanced MIDI file exported to: {filename}")

        dialog.destroy()

    def generate_structured_patterns(self, style, duration, bpm, unique=False):
        # Definicja struktury sekcji z mniej gwałtownymi przejściami w intensywności
        structure = {
            "intro": random.randint(4, 6) if unique else 4,
            "verse1": random.randint(12, 14) if unique else 14,
            "chorus1": random.randint(6, 8) if unique else 8,
            "verse2": random.randint(12, 14) if unique else 14,
            "chorus2": random.randint(6, 8) if unique else 8,
            "development": random.randint(12, 14) if unique else 12,
            "chorus3": random.randint(6, 8) if unique else 8,
            "outro": random.randint(4, 6) if unique else 4
        }

        # Obliczenia dla dopasowania liczby miar, jak wcześniej
        total_measures = int(duration * bpm / 60 / 4)
        total_structure_measures = sum(structure.values())
        if total_structure_measures < total_measures:
            structure["outro"] += total_measures - total_structure_measures
        elif total_structure_measures > total_measures:
            structure["outro"] = max(4, structure["outro"] - (total_structure_measures - total_measures))

        patterns = {}
        current_measure = 0

        for section, section_measures in structure.items():
            section_duration = section_measures * 4 * 60 / bpm
            drum_pattern = self.generate_drum_pattern(style, section_duration, bpm)
            bass_pattern = self.generate_bass_pattern(style, section_duration, bpm)
            lead_pattern = self.generate_lead_pattern(style, section_duration, bpm)

            # Zmniejszamy intensywność sekcji poprzez zastosowanie mniejszego zagęszczenia instrumentów w "intro" i "outro"
            if "intro" in section or "outro" in section:
                drum_pattern = self.simplify_pattern(drum_pattern)
                bass_pattern = self.simplify_pattern(bass_pattern)
                lead_pattern = self.simplify_pattern(lead_pattern)
            elif "development" in section:
                drum_pattern = self.intensify_pattern(drum_pattern)
                bass_pattern = self.intensify_pattern(bass_pattern)
                lead_pattern = self.intensify_pattern(lead_pattern)

            patterns[section] = {
                "drums": drum_pattern,
                "bass": bass_pattern,
                "lead": lead_pattern,
                "start_measure": current_measure,
                "duration": section_measures
            }
            current_measure += section_measures

        return patterns

    def simplify_pattern(self, pattern):
        if isinstance(pattern, dict):  # For drum patterns
            for inst in pattern:
                pattern[inst] = [x if i % 2 == 0 else 0 for i, x in enumerate(pattern[inst])]
        else:  # For bass and lead patterns
            pattern = [x if i % 2 == 0 else 0 for i, x in enumerate(pattern)]
        return pattern

    def intensify_pattern(self, pattern):
        if isinstance(pattern, dict):  # For drum patterns
            for inst in pattern:
                pattern[inst] = [x if x != 0 else random.choice([0, 1]) for x in pattern[inst]]
        else:  # For bass and lead patterns
            pattern = [x if x != 0 else random.choice([0, random.choice([60, 62, 64, 65, 67, 69, 71, 72])]) for x in pattern]
        return pattern

    def add_structured_notes(self, midi, structured_patterns, dynamic_bpm):
        time = 0
        current_bpm_index = 0
        steps_per_bpm = 4

        for section, patterns in structured_patterns.items():
            drum_pattern = patterns['drums']
            bass_pattern = patterns['bass']
            lead_pattern = patterns['lead']
            section_duration = patterns['duration'] * 4  # 4 steps per measure

            for step in range(section_duration):
                if step % steps_per_bpm == 0:
                    current_bpm = dynamic_bpm[current_bpm_index] * self.absolute_bpm / 100
                    current_bpm_index = (current_bpm_index + 1) % len(dynamic_bpm)

                # Add drum notes
                for inst in self.instruments:
                    if drum_pattern[inst][step % len(drum_pattern[inst])] == 1:
                        midi.addNote(0, 9, self.midi_notes[inst], time, 0.25, 100)

                # Add bass notes
                bass_note = bass_pattern[step % len(bass_pattern)]
                if bass_note != 0:
                    midi.addNote(1, 0, bass_note, time, 0.5, 80)

                # Add lead notes
                lead_note = lead_pattern[step % len(lead_pattern)]
                if lead_note != 0:
                    midi.addNote(2, 1, lead_note, time, 0.25, 90)

                time += 60 / current_bpm / 4

    def generate_drum_pattern(self, style, duration, bpm):
        # Długość patternu w zależności od czasu trwania i BPM
        pattern_length = int(duration * bpm / 60 / 4)
        pattern = {inst: [0] * pattern_length for inst in self.instruments}

        if style == "Techno":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 4 == 0 else 0
                pattern['Werbel'][i] = 1 if i % 8 == 4 else 0
                # Zmniejszamy ilość talerzy, np. co 4 krok zamiast co 2
                pattern['Talerz'][i] = 1 if i % 4 == 2 and random.random() < 0.3 else 0
                # Mniejsza losowość TomTom, pojawiają się co 16 kroków
                pattern['TomTom'][i] = 1 if i % 16 == 14 and random.random() < 0.3 else 0
        elif style == "House":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 4 in [0, 2] else 0
                pattern['Werbel'][i] = 1 if i % 8 == 4 else 0
                # Talerz z mniejszą częstotliwością
                pattern['Talerz'][i] = 1 if i % 8 == 4 and random.random() < 0.25 else 0
                pattern['TomTom'][i] = 1 if i % 16 == 12 else 0
        elif style == "Drum and Bass":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 8 in [0, 3] else 0
                pattern['Werbel'][i] = 1 if i % 8 == 4 else 0
                # Rzadziej używany Talerz dla lepszej dynamiki
                pattern['Talerz'][i] = 1 if i % 16 == 8 and random.random() < 0.2 else 0
                pattern['TomTom'][i] = 1 if i % 16 == 10 else 0
        elif style == "Ambient":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 16 == 0 else 0
                pattern['Werbel'][i] = 1 if i % 32 == 16 else 0
                # Talerz tylko na kilku krokach
                pattern['Talerz'][i] = 1 if i % 16 == 8 and random.random() < 0.2 else 0
                pattern['TomTom'][i] = 1 if i % 64 == 48 else 0

        return pattern

    def generate_bass_pattern(self, style, duration, bpm):
        pattern_length = int(duration * bpm / 60 / 4)
        pattern = [0] * pattern_length

        if style == "Techno":
            for i in range(pattern_length):
                pattern[i] = random.choice([36, 38, 41, 43]) if i % 4 == 0 else 0
        elif style == "House":
            for i in range(pattern_length):
                pattern[i] = random.choice([36, 38, 41, 43]) if i % 2 == 0 else 0
        elif style == "Drum and Bass":
            for i in range(pattern_length):
                pattern[i] = random.choice([36, 38, 41, 43, 45]) if i % 8 in [0, 3, 6] else 0
        elif style == "Ambient":
            for i in range(pattern_length):
                pattern[i] = random.choice([36, 38, 41]) if i % 16 == 0 else 0

        return pattern

    def generate_lead_pattern(self, style, duration, bpm):
        pattern_length = int(duration * bpm / 60 / 4)
        pattern = [0] * pattern_length

        if style == "Techno":
            for i in range(pattern_length):
                pattern[i] = random.choice([60, 62, 64, 65, 67]) if i % 8 in [0, 3, 5] else 0
        elif style == "House":
            for i in range(pattern_length):
                pattern[i] = random.choice([60, 62, 64, 65]) if i % 4 in [0, 2] else 0
        elif style == "Drum and Bass":
            for i in range(pattern_length):
                pattern[i] = random.choice([60, 62, 64, 67, 69]) if i % 16 in [0, 3, 6] else 0
        elif style == "Ambient":
            for i in range(pattern_length):
                pattern[i] = random.choice([60, 62, 64]) if i % 32 in [0, 8, 16] else 0

        return pattern

    def add_drum_notes(self, midi, pattern, dynamic_bpm):
        track = 0
        time = 0
        current_bpm_index = 0
        steps_per_bpm = 4

        for step in range(len(pattern['Stopa'])):
            if step % steps_per_bpm == 0:
                current_bpm = dynamic_bpm[current_bpm_index]
                current_bpm_index = (current_bpm_index + 1) % len(dynamic_bpm)

            for inst in self.instruments:
                if pattern[inst][step] == 1:
                    midi.addNote(track, 9, self.midi_notes[inst], time, 0.25, 100)

            time += 60 / current_bpm / 4

    def add_bass_notes(self, midi, pattern, dynamic_bpm):
        track = 1
        time = 0
        current_bpm_index = 0
        steps_per_bpm = 4

        for step, note in enumerate(pattern):
            if step % steps_per_bpm == 0:
                current_bpm = dynamic_bpm[current_bpm_index]
                current_bpm_index = (current_bpm_index + 1) % len(dynamic_bpm)

            if note != 0:
                midi.addNote(track, 0, note, time, 0.5, 80)

            time += 60 / current_bpm / 4

    def add_lead_notes(self, midi, pattern, dynamic_bpm):
        track = 2
        time = 0
        current_bpm_index = 0
        steps_per_bpm = 4

        for step, note in enumerate(pattern):
            if step % steps_per_bpm == 0:
                current_bpm = dynamic_bpm[current_bpm_index]
                current_bpm_index = (current_bpm_index + 1) % len(dynamic_bpm)

            if note != 0:
                midi.addNote(track, 1, note, time, 0.25, 90)

            time += 60 / current_bpm / 4

    # Adding AI Composer method
    def apply_generated_pattern(self, generated_text):
        """
        Parse the AI-generated pattern text and apply it to the drum machine.
        """
        print(f"Parsing generated text: {generated_text}")  # Debugging

        # Initialize patterns with zeros
        pattern_length = int(self.length_spinbutton.get_value())
        for inst in self.instruments:
            self.patterns[inst] = [0] * pattern_length

        # Process only the lines containing instrument patterns
        lines = generated_text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:  # Skip empty lines
                continue

            try:
                # Split line into instrument name and pattern
                parts = line.split(':')
                if len(parts) != 2:
                    continue

                instrument_name = parts[0].strip()
                pattern_str = parts[1].strip()

                # Skip if this isn't one of our instruments
                if instrument_name not in self.instruments:
                    continue

                # Convert pattern string to list of integers
                pattern = []
                for digit in pattern_str.split():
                    if digit in ['0', '1']:
                        pattern.append(int(digit))

                # Ensure pattern matches expected length
                if pattern:
                    pattern = pattern[:pattern_length]  # Truncate if too long
                    while len(pattern) < pattern_length:  # Extend if too short
                        pattern.append(0)

                    # Apply the pattern
                    self.patterns[instrument_name] = pattern

            except Exception as e:
                print(f"Error processing line '{line}': {e}")
                continue

        # Update the UI
        self.update_buttons()

    def generate_ai_pattern(self, widget):
        genre = self.genre_entry.get_text()

        # Check database for existing pattern
        self.cursor.execute("SELECT logic FROM patterns WHERE genre=?", (genre,))
        row = self.cursor.fetchone()

        pattern_logic = None
        if row:
            pattern_logic = row[0]
            print(f"Found saved pattern for {genre}")

        if not pattern_logic:
            print(f"Generating new pattern for {genre}")
            pattern_logic = self.ai_composer.generate_pattern(genre)
            if pattern_logic:  # Save only if we got a valid pattern
                self.cursor.execute("INSERT INTO patterns (genre, logic) VALUES (?, ?)",
                                  (genre, pattern_logic))
                self.conn.commit()

        if pattern_logic:
            self.apply_generated_pattern(pattern_logic)
        else:
            print("Failed to generate or retrieve pattern")


class AIComposer:
    def __init__(self):
        self.api_url = "http://localhost:11434/api/generate"
        self.model = "llama3.2"

    def generate_pattern(self, genre="Disco", steps=16):
        prompt = f"Generate a {steps}-step drum pattern for {genre} music. For each instrument provide only numbers (0 or 1) separated by spaces. Format:\nStopa: 1 0 1 0...\nWerbel: 0 1 0 1...\nTalerz: 1 1 0 0...\nTomTom: 0 0 1 1..."

        data = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }

        try:
            response = requests.post(self.api_url, json=data)
            response.raise_for_status()

            generated_text = response.json()['response']
            print(f"Raw AI response: {generated_text}")  # Debugging

            # Ensure we have valid response before returning
            if not any(inst in generated_text for inst in ['Stopa:', 'Werbel:', 'Talerz:', 'TomTom:']):
                print("Invalid response from AI, using default pattern")
                return self.get_default_pattern(steps)

            return generated_text

        except requests.exceptions.RequestException as e:
            print(f"Error communicating with Ollama: {e}")
            return self.get_default_pattern(steps)

    def get_default_pattern(self, steps):
        return f"""Stopa: {' '.join(['1', '0'] * (steps // 2))}
Werbel: {' '.join(['0', '1'] * (steps // 2))}
Talerz: {' '.join(['1', '1', '0', '0'] * (steps // 4))}
TomTom: {' '.join(['0', '0', '1', '1'] * (steps // 4))}"""

win = DrumSamplerApp()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
