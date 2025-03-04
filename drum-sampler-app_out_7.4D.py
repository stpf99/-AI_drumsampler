import gi
import random
import time
import threading
import pygame
import json
import os
from midiutil import MIDIFile
from pydub import AudioSegment
from pydub.effects import normalize
import numpy as np
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk
import warnings
warnings.filterwarnings("ignore", category=SyntaxWarning)
import sqlite3
import librosa
import soundfile as sf

class DrumSamplerApp(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Drum Sampler")
        self.set_border_width(10)
        self.set_default_size(1280, 720)
        self.is_fullscreen = False

        pygame.mixer.init()

        # Main container
        scroll_window = Gtk.ScrolledWindow()
        scroll_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroll_window.add(self.main_box)
        self.add(scroll_window)

        # Base settings
        self.base_bpm = 80
        self.absolute_bpm = 120
        self.genre_bpm = {"House": 125, "Techno": 130, "Drum and Bass": 165, "Ambient": 80}
        self.instruments = ['Talerz', 'Stopa', 'Werbel', 'TomTom']
        self.patterns = {inst: [0] * 16 for inst in self.instruments}
        self.colors = ['red', 'green', 'blue', 'orange']
        self.midi_notes = {'Talerz': 49, 'Stopa': 36, 'Werbel': 38, 'TomTom': 45}
        self.buttons = {}
        self.samples = {}
        self.effects = {inst: {'volume': 0, 'pitch': 0, 'echo': 0, 'reverb': 0, 'pan': 0} for inst in self.instruments}

        # Load samples
        self.load_samples_from_directory()

        # UI setup
        self.create_toolbar()
        self.grid = Gtk.Grid()
        self.main_box.pack_start(self.grid, True, True, 0)

        # Grid setup
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
        self.dynamic_bpm_list = []
        self.current_bpm_index = 0
        self.steps_per_bpm = 4

        # Connect scaling
        self.connect("size-allocate", self.scale_interface)

        self.effect_sliders = {}
        self.groove_type = 'simple'

        # Additional controls
        self.add_css()
        self.create_groove_controls()
        self.create_drummer_to_audio_button()
        self.create_bpm_controls()
        self.create_matched_bpm_control()
        self.create_dynamic_bpm_control()
        self.create_pattern_controls()
        self.create_pattern_length_control()
        self.create_instrument_randomization_controls()
        self.create_preset_selection()
        self.create_autolevel_button()
        self.create_effect_controls()

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
            ("document-export", self.export_advanced_midi, "Export Advanced MIDI")
        ]

        for icon_name, callback, tooltip in button_info:
            button = Gtk.ToolButton()
            button.set_icon_name(icon_name)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", callback)
            toolbar.insert(button, -1)

        fullscreen_button = Gtk.ToolButton.new(None, "Wejdź w pełny ekran")
        fullscreen_button.connect("clicked", self.toggle_fullscreen)
        toolbar.insert(fullscreen_button, -1)

        audio_backend_label = Gtk.Label(label="Audio Backend:")
        toolbar.insert(Gtk.ToolItem(), -1)
        audio_backend_item = Gtk.ToolItem()
        backend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        self.backend_combo = Gtk.ComboBoxText()
        self.backend_combo.append_text("PipeWire")
        self.backend_combo.append_text("JACK")
        self.backend_combo.set_active(0)

        backend_box.pack_start(audio_backend_label, False, False, 0)
        backend_box.pack_start(self.backend_combo, False, False, 0)
        audio_backend_item.add(backend_box)
        toolbar.insert(audio_backend_item, -1)
        toolbar.show_all()

    def add_css(self):
        css_provider = Gtk.CssProvider()
        css = """
        .circle-red, .circle-green, .circle-blue, .circle-orange {
            border-radius: 15px;
            background-color: white;
        }
        .circle-red:active { background-color: red; }
        .circle-green:active { background-color: green; }
        .circle-blue:active { background-color: blue; }
        .circle-orange:active { background-color: orange; }
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

    def on_button_toggled(self, button, instrument, step):
        self.patterns[instrument][step] = int(button.get_active())

    def update_buttons(self):
        pattern_length = int(self.length_spinbutton.get_value())
        for inst in self.instruments:
            for i in range(pattern_length):
                self.buttons[inst][i].set_active(bool(self.patterns[inst][i]))

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
        bpm_up_button.connect("clicked", self.bpm_step_up)
        bpm_box.pack_start(bpm_up_button, False, False, 0)

        bpm_down_button = Gtk.Button()
        bpm_down_button.set_image(Gtk.Image.new_from_icon_name("go-down", Gtk.IconSize.SMALL_TOOLBAR))
        bpm_down_button.connect("clicked", self.bpm_step_down)
        bpm_box.pack_start(bpm_down_button, False, False, 0)

    def bpm_step_up(self, widget):
        self.absolute_bpm = min(300, self.absolute_bpm + 5)
        self.bpm_entry.set_text(str(self.absolute_bpm))
        self.update_dynamic_bpm()

    def bpm_step_down(self, widget):
        self.absolute_bpm = max(60, self.absolute_bpm - 5)
        self.bpm_entry.set_text(str(self.absolute_bpm))
        self.update_dynamic_bpm()

    def create_matched_bpm_control(self):
        bpm_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(bpm_box, False, False, 0)

        matched_bpm_button = Gtk.Button(label="Matched BPM")
        matched_bpm_button.connect("clicked", self.matched_bpm)
        bpm_box.pack_start(matched_bpm_button, False, False, 0)

        perfect_bpm_button = Gtk.Button(label="Perfect Tempo BPM")
        perfect_bpm_button.connect("clicked", self.perfect_tempo_bpm)
        bpm_box.pack_start(perfect_bpm_button, False, False, 0)

    def calculate_pattern_density(self):
        total_active_steps = sum(sum(steps) for steps in self.patterns.values())
        total_steps = sum(len(steps) for steps in self.patterns.values())
        return total_active_steps / total_steps if total_steps > 0 else 0

    def matched_bpm(self, widget):
        density = self.calculate_pattern_density()
        new_bpm = self.base_bpm + (density - 0.5) * 80
        self.absolute_bpm = int(new_bpm)
        self.bpm_entry.set_text(str(self.absolute_bpm))

    def perfect_tempo_bpm(self, widget):
        self.matched_bpm(widget)
        genre = self.custom_genre_entry.get_text()
        avg_bpm = self.genre_bpm.get(genre, self.base_bpm)
        self.absolute_bpm = int((self.absolute_bpm + avg_bpm) / 2)
        self.bpm_entry.set_text(str(self.absolute_bpm))

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

    def create_pattern_controls(self):
        genre_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(genre_box, False, False, 0)

        # Predefined genres
        preset_label = Gtk.Label(label="FX Genre:")
        genre_box.pack_start(preset_label, False, False, 0)

        self.preset_genre_combo = Gtk.ComboBoxText()
        genres = ["House", "Techno", "Drum and Bass", "Ambient", "Trap", "Dubstep", "Jazz", "Breakbeat"]
        for genre in genres:
            self.preset_genre_combo.append_text(genre)
        self.preset_genre_combo.set_active(0)
        genre_box.pack_start(self.preset_genre_combo, False, False, 0)

        auto_fx_button = Gtk.Button(label="Auto FX Style")
        auto_fx_button.connect("clicked", self.apply_auto_fx_for_selected_style)
        genre_box.pack_start(auto_fx_button, False, False, 0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        genre_box.pack_start(separator, False, False, 10)

        # Custom genre
        custom_label = Gtk.Label(label="Custom Genre:")
        genre_box.pack_start(custom_label, False, False, 0)

        self.custom_genre_entry = Gtk.Entry()
        genre_box.pack_start(self.custom_genre_entry, False, False, 0)

        # Progression type
        progression_label = Gtk.Label(label="Progression:")
        genre_box.pack_start(progression_label, False, False, 0)
        self.progression_combo = Gtk.ComboBoxText()
        progressions = ["Linear", "Dense", "Sparse", "Random"]
        for p in progressions:
            self.progression_combo.append_text(p)
        self.progression_combo.set_active(0)
        genre_box.pack_start(self.progression_combo, False, False, 0)

        # Occurrences
        occurrences_label = Gtk.Label(label="Occurrences:")
        genre_box.pack_start(occurrences_label, False, False, 0)
        self.occurrences_spin = Gtk.SpinButton()
        self.occurrences_spin.set_adjustment(Gtk.Adjustment(value=4, lower=1, upper=16, step_increment=1))
        genre_box.pack_start(self.occurrences_spin, False, False, 0)

        # Intensity
        intensity_label = Gtk.Label(label="Intensity:")
        genre_box.pack_start(intensity_label, False, False, 0)
        self.intensity_spin = Gtk.SpinButton()
        self.intensity_spin.set_adjustment(Gtk.Adjustment(value=0.5, lower=0, upper=1, step_increment=0.1))
        genre_box.pack_start(self.intensity_spin, False, False, 0)

        generate_button = Gtk.Button(label="Generate Pattern")
        generate_button.connect("clicked", self.generate_custom_pattern)
        genre_box.pack_start(generate_button, False, False, 0)

        genre_box.show_all()

    def generate_custom_pattern(self, widget):
        genre = self.custom_genre_entry.get_text()
        progression = self.progression_combo.get_active_text()
        occurrences = int(self.occurrences_spin.get_value())
        intensity = self.intensity_spin.get_value()
        pattern_length = int(self.length_spinbutton.get_value())

        for inst in self.instruments:
            self.patterns[inst] = [0] * pattern_length

        if progression == "Linear":
            for inst in self.instruments:
                step_interval = pattern_length // occurrences
                for i in range(0, pattern_length, step_interval):
                    if random.random() < intensity:
                        self.patterns[inst][i] = 1
        elif progression == "Dense":
            for inst in self.instruments:
                for i in range(pattern_length):
                    if random.random() < intensity * 0.8:
                        self.patterns[inst][i] = 1
        elif progression == "Sparse":
            for inst in self.instruments:
                for i in range(pattern_length):
                    if random.random() < intensity * 0.3:
                        self.patterns[inst][i] = 1
        elif progression == "Random":
            for inst in self.instruments:
                for i in range(pattern_length):
                    if random.random() < intensity:
                        self.patterns[inst][i] = 1

        self.update_buttons()
        print(f"Generated pattern for {genre} with {progression}, {occurrences} occurrences, intensity {intensity}")

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

        for i in range(new_length):
            label = self.grid.get_child_at(i + 1, 0)
            if label is None:
                label = Gtk.Label(label=str(i + 1))
                self.grid.attach(label, i + 1, 0, 1, 1)
            else:
                label.set_visible(True)

        for i in range(new_length, 32):
            label = self.grid.get_child_at(i + 1, 0)
            if label:
                label.set_visible(False)

        self.grid.show_all()

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

        autofill_button = Gtk.Button(label="Autofill")
        autofill_button.connect("clicked", lambda widget: self.autofill_pattern())
        randomize_box.pack_start(autofill_button, False, False, 0)

    def randomize_instruments(self, widget):
        probability = self.randomize_probability_spin.get_value() / 100
        pattern_length = int(self.length_spinbutton.get_value())

        for step in range(pattern_length):
            if random.random() < probability:
                inst1, inst2 = random.sample(self.instruments, 2)
                self.patterns[inst1][step], self.patterns[inst2][step] = self.patterns[inst2][step], self.patterns[inst1][step]

        self.update_buttons()

    def autofill_pattern(self):
        pattern_length = int(self.length_spinbutton.get_value())
        
        for instrument, steps in self.patterns.items():
            active_steps = [i for i, step in enumerate(steps) if step == 1]
    
            for i in range(pattern_length):
                if i not in active_steps:
                    neighbors = [
                        steps[(i - 1) % pattern_length],
                        steps[(i + 1) % pattern_length]
                    ]
                    if sum(neighbors) > 0 or random.random() < 0.3:
                        steps[i] = random.choice([0, 1]) if random.random() < 0.7 else steps[i]
    
            for i in range(pattern_length):
                if instrument == 'Stopa' and i % 4 == 0:
                    steps[i] = 1
                elif instrument == 'Werbel' and i % 8 == 4:
                    steps[i] = 1
                elif instrument == 'Talerz' and random.random() < 0.2:
                    steps[i] = random.choice([0, 1])
                elif instrument == 'TomTom' and i % 16 == 7:
                    steps[i] = random.choice([0, 1])
        
        self.update_buttons()

    def create_preset_selection(self):
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(preset_box, False, False, 0)

        preset_label = Gtk.Label(label="Genre Preset:")
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

    def create_autolevel_button(self):
        autolevel_button = Gtk.Button(label="Auto Level")
        autolevel_button.connect("clicked", self.autolevel_samples)
        self.main_box.pack_start(autolevel_button, False, False, 0)

    def create_effect_controls(self):
        effect_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        effect_box.set_hexpand(True)
        self.main_box.pack_start(effect_box, False, False, 0)

        effect_label = Gtk.Label(label="Audio Effects")
        effect_box.pack_start(effect_label, False, False, 0)

        effect_grid = Gtk.Grid()
        effect_grid.set_column_spacing(10)
        effect_box.pack_start(effect_grid, True, True, 0)

        effects = ['Volume', 'Pitch', 'Echo', 'Reverb', 'Pan']
        for col, effect in enumerate(effects, start=1):
            label = Gtk.Label(label=effect)
            effect_grid.attach(label, col, 0, 1, 1)

        for row, instrument in enumerate(self.instruments, start=1):
            label = Gtk.Label(label=instrument)
            effect_grid.attach(label, 0, row, 1, 1)
            self.effect_sliders[instrument] = {}

            for col, effect in enumerate(effects, start=1):
                adjustment = Gtk.Adjustment(value=0, lower=-2, upper=2, step_increment=0.1)
                slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
                slider.set_digits(1)
                slider.set_hexpand(True)
                slider.connect('value-changed', self.on_effect_changed, instrument, effect.lower())
                effect_grid.attach(slider, col, row, 1, 1)
                self.effect_sliders[instrument][effect.lower()] = slider

                reset_button = Gtk.Button(label="Reset")
                reset_button.set_size_request(60, 35)
                reset_button.connect('clicked', self.reset_effect, slider, instrument, effect.lower())
                effect_grid.attach_next_to(reset_button, slider, Gtk.PositionType.RIGHT, 1, 1)

    def on_effect_changed(self, slider, instrument, effect):
        value = slider.get_value()
        self.effects[instrument][effect] = value
        print(f"Changed {effect} for {instrument} to {value}")

    def reset_effect(self, button, slider, instrument, effect):
        slider.set_value(0)
        self.effects[instrument][effect] = 0
        print(f"Reset {effect} for {instrument} to 0")

    def apply_effects(self, sound, instrument):
        effects = self.effects[instrument]

        sound_array = pygame.sndarray.array(sound)
        sample_width = sound_array.dtype.itemsize
        channels = 1 if sound_array.ndim == 1 else 2

        audio_segment = AudioSegment(
            sound_array.tobytes(),
            frame_rate=44100,
            sample_width=sample_width,
            channels=channels
        )

        if effects['volume'] != 0:
            audio_segment = audio_segment + (effects['volume'] * 10)

        if effects['pitch'] != 0:
            new_rate = int(audio_segment.frame_rate * (2 ** (effects['pitch'] / 12)))
            audio_segment = audio_segment._spawn(audio_segment.raw_data, overrides={'frame_rate': new_rate})
            audio_segment = audio_segment.set_frame_rate(44100)

        if effects['echo'] > 0:
            delay_ms = int(200 * effects['echo'])
            echo_segment = audio_segment - 10
            audio_segment = audio_segment.overlay(echo_segment, position=delay_ms)

        if effects['reverb'] > 0:
            reverb_amount = effects['reverb'] * 300
            audio_segment = audio_segment.fade_in(50).fade_out(int(reverb_amount))

        if effects['pan'] != 0:
            audio_segment = audio_segment.pan(effects['pan'])

        audio_segment = normalize(audio_segment)

        samples = np.array(audio_segment.get_array_of_samples())
        if channels == 2:
            samples = samples.reshape((-1, 2))

        return pygame.sndarray.make_sound(samples)

    def apply_auto_fx_for_style(self, style):
        fx_settings = {
            "Techno": {'volume': 0.5, 'pitch': 0.2, 'echo': 1.0, 'reverb': 1.2, 'pan': 0.0},
            "House": {'volume': 0.3, 'pitch': 0.0, 'echo': 0.5, 'reverb': 1.0, 'pan': 0.2},
            "Drum and Bass": {'volume': 1.0, 'pitch': -0.5, 'echo': 0.8, 'reverb': 0.7, 'pan': -0.1},
            "Ambient": {'volume': -0.5, 'pitch': 0.0, 'echo': 1.0, 'reverb': 1.5, 'pan': 0.3},
            "Trap": {'volume': 0.8, 'pitch': -1.0, 'echo': 0.6, 'reverb': 0.5, 'pan': -0.2},
            "Dubstep": {'volume': 1.2, 'pitch': -0.8, 'echo': 1.2, 'reverb': 1.0, 'pan': 0.1},
            "Jazz": {'volume': 0.4, 'pitch': 0.3, 'echo': 0.2, 'reverb': 0.8, 'pan': 0.4},
            "Breakbeat": {'volume': 0.7, 'pitch': 0.1, 'echo': 0.9, 'reverb': 0.6, 'pan': -0.3}
        }
        settings = fx_settings.get(style, {})
        for instrument in self.instruments:
            for effect, value in settings.items():
                self.effects[instrument][effect] = value
                if effect in self.effect_sliders[instrument]:
                    self.effect_sliders[instrument][effect].set_value(value)

    def apply_auto_fx_for_selected_style(self, widget):
        selected_style = self.preset_genre_combo.get_active_text()
        if selected_style:
            self.apply_auto_fx_for_style(selected_style)
            print(f"Applied auto FX for style: {selected_style}")

    def create_groove_controls(self):
        groove_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(groove_box, False, False, 0)

        groove_label = Gtk.Label(label="Groove Type:")
        groove_box.pack_start(groove_label, False, False, 0)

        self.groove_combo = Gtk.ComboBoxText()
        groove_types = ["simple", "stretch", "echoes", "bouncy", "relax"]
        for groove in groove_types:
            self.groove_combo.append_text(groove)
        self.groove_combo.set_active(0)
        groove_box.pack_start(self.groove_combo, False, False, 0)

        groove_button = Gtk.Button(label="Apply Groove")
        groove_button.connect("clicked", self.apply_groove)
        groove_box.pack_start(groove_button, False, False, 0)

    def apply_groove(self, widget):
        self.groove_type = self.groove_combo.get_active_text()
        print(f"Applied groove: {self.groove_type}")
        self.play_pattern(widget)

    def apply_groove_effects(self, sound, instrument, step):
        if self.groove_type == "simple":
            return self.apply_simple_groove(sound, instrument, step)
        elif self.groove_type == "stretch":
            return self.apply_stretch_groove(sound, instrument, step)
        elif self.groove_type == "echoes":
            return self.apply_echoes_groove(sound, instrument, step)
        elif self.groove_type == "bouncy":
            return self.apply_bouncy_groove(sound, instrument, step)
        elif self.groove_type == "relax":
            return self.apply_relax_groove(sound, instrument, step)
        return sound

    def apply_simple_groove(self, sound, instrument, step):
        repeat_chance = random.randint(1, 3)
        if repeat_chance == 2:
            print(f"Repeating {instrument} at step {step}")
            sound.play()
        return sound

    def apply_stretch_groove(self, sound, instrument, step):
        stretched_bpm = self.get_next_bpm() * random.uniform(0.9, 1.1)
        self.advance_bpm()
        print(f"Stretched BPM: {stretched_bpm}")
        return sound

    def apply_echoes_groove(self, sound, instrument, step):
        print(f"Applying echoes to {instrument} at step {step}")
        return self.apply_effects_with_echo(sound, instrument)

    def apply_bouncy_groove(self, sound, instrument, step):
        volume_factor = random.choice([0.8, 1.2])
        sound.set_volume(volume_factor)
        print(f"Bouncy volume for {instrument}: {volume_factor}")
        return sound

    def apply_relax_groove(self, sound, instrument, step):
        print(f"Relaxing groove for {instrument}")
        return self.apply_effects_with_echo(sound, instrument)

    def apply_effects_with_echo(self, sound, instrument):
        effect_sound = pygame.mixer.Sound(self.samples[instrument])
        effect_sound.play(maxtime=500)
        return sound

    def create_drummer_to_audio_button(self):
        drummer_button = Gtk.Button(label="Add Drummer to Audio")
        drummer_button.connect("clicked", self.add_drummer_to_audio)
        self.main_box.pack_start(drummer_button, False, False, 0)

    def add_drummer_to_audio(self, widget):
        file_dialog = Gtk.FileChooserDialog(title="Select Audio File", parent=self)
        file_dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)

        progress_dialog = Gtk.Dialog(title="Generating Percussion", transient_for=self, modal=True)
        progress_dialog.set_default_size(300, 100)

        progress_bar = Gtk.ProgressBar()
        progress_bar.set_show_text(True)
        progress_dialog.get_content_area().pack_start(progress_bar, True, True, 0)
        progress_dialog.show_all()

        def update_progress(fraction, message):
            GLib.idle_add(progress_bar.set_fraction, fraction)
            GLib.idle_add(progress_bar.set_text, message)

        def generate_drums_thread(audio_path):
            try:
                update_progress(0.1, "Analyzing audio structure...")
                y, sr = librosa.load(audio_path, sr=22050)
                tempo = librosa.beat.beat_track(y=y, sr=sr)[0]

                update_progress(0.3, "Detecting rhythmic patterns...")
                segments = librosa.effects.split(y, top_db=30)

                if len(segments) < 2:
                    raise ValueError("Not enough segments found for processing.")

                update_progress(0.5, "Generating percussion track...")
                percussion_track, original_audio, sr = self.advanced_generate_drum_track(audio_path)

                update_progress(0.7, "Synthesizing audio...")
                percussion_audio = self.synthesize_percussion_audio(percussion_track, sr, original_audio)

                update_progress(0.9, "Saving tracks...")
                self.save_generated_tracks(audio_path, percussion_track, original_audio, sr)

                GLib.idle_add(progress_dialog.destroy)
                GLib.idle_add(self.show_save_confirmation,
                              audio_path.replace(".mp3", "_complementary_drums.wav"),
                              audio_path.replace(".mp3", "_combined.wav"))
            except Exception as e:
                GLib.idle_add(progress_dialog.destroy)
                GLib.idle_add(self.show_error_dialog, str(e))

        response = file_dialog.run()
        if response == Gtk.ResponseType.OK:
            audio_path = file_dialog.get_filename()
            file_dialog.destroy()
            threading.Thread(target=generate_drums_thread, args=(audio_path,), daemon=True).start()
        else:
            file_dialog.destroy()

    def advanced_generate_drum_track(self, audio_path):
        y, sr = librosa.load(audio_path, sr=22050)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        segments = librosa.effects.split(y, top_db=30)

        if len(segments) < 2:
            raise ValueError("Not enough segments for drum generation.")

        steps_per_beat = 8
        total_duration = librosa.get_duration(y=y, sr=sr)
        bars = int(total_duration * (tempo / 60))
        total_steps = bars * steps_per_beat

        percussion_track = {inst: [0] * total_steps for inst in self.instruments}

        for segment_idx, (start, end) in enumerate(zip(segments[:-1], segments[1:])):
            segment_start_step = int(segment_idx * total_steps / len(segments))
            segment_end_step = int((segment_idx + 1) * total_steps / len(segments))

            for inst in self.instruments:
                for step in range(segment_start_step, segment_end_step):
                    percussion_track[inst][step] = random.randint(0, 1)

        return percussion_track, y, sr

    def synthesize_percussion_audio(self, percussion_track, sr, original_audio):
        tempo = librosa.beat.beat_track(y=original_audio, sr=sr)[0]
        total_length = len(percussion_track['Stopa'])
        step_duration = int(sr * 60 / tempo / 4)

        audio = np.zeros(total_length * step_duration, dtype=np.float32)

        for inst in self.instruments:
            trigger_steps = np.where(np.array(percussion_track[inst]) == 1)[0]
            for step in trigger_steps:
                try:
                    sample = pygame.mixer.Sound(self.samples[inst])
                    sample_array = pygame.sndarray.array(sample)
                    if sample_array.ndim > 1:
                        sample_array = sample_array.mean(axis=1)
                    if len(sample_array) > step_duration:
                        sample_array = sample_array[:step_duration]
                    elif len(sample_array) < step_duration:
                        sample_array = np.pad(sample_array, (0, max(0, step_duration - len(sample_array))))
                    start = step * step_duration
                    end = start + step_duration
                    audio[start:end] += sample_array
                except Exception as e:
                    print(f"Error processing {inst} sample: {e}")

        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio /= max_val

        return audio

    def save_generated_tracks(self, audio_path, percussion_track, original_audio, sr):
        percussion_audio = self.synthesize_percussion_audio(percussion_track, sr, original_audio)
        max_length = len(original_audio)
        percussion_audio = librosa.util.fix_length(percussion_audio, size=max_length)
        combined_audio = (original_audio * 0.7 + percussion_audio * 0.3)
        combined_audio = librosa.util.normalize(combined_audio)

        percussion_path = audio_path.replace(".mp3", "_complementary_drums.wav")
        combined_path = audio_path.replace(".mp3", "_combined.wav")

        sf.write(percussion_path, percussion_audio, sr)
        sf.write(combined_path, combined_audio, sr)

        return percussion_path, combined_path

    def show_save_confirmation(self, percussion_path, combined_path):
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            message_format="Tracks successfully saved!"
        )
        dialog.format_secondary_text(f"Percussion Track: {percussion_path}\nCombined Track: {combined_path}")
        dialog.run()
        dialog.destroy()

    def show_error_dialog(self, message):
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            message_format="Error occurred!"
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def scale_interface(self, widget, allocation):
        width, height = allocation.width, allocation.height
        scale_factor = min(width / 1280, height / 720)

        button_size = int(30 * scale_factor)
        for row in self.buttons.values():
            for button in row:
                button.set_size_request(button_size, button_size)

        self.grid.set_row_spacing(int(6 * scale_factor))
        self.grid.set_column_spacing(int(6 * scale_factor))

    def load_samples_from_directory(self):
        sample_dir = "sample"
        if not os.path.exists(sample_dir):
            print("Katalog 'sample' nie istnieje. Pomijam automatyczne wczytywanie.")
            return

        for instrument in self.instruments:
            file_path = os.path.join(sample_dir, f"{instrument}.wav")
            if os.path.isfile(file_path):
                self.samples[instrument] = file_path
                print(f"Załadowano sample dla {instrument}: {file_path}")
            else:
                print(f"Brak sampla dla {instrument}. Pomijam.")

    def toggle_fullscreen(self, button):
        if self.is_fullscreen:
            self.unfullscreen()
            self.is_fullscreen = False
            button.set_label("Wejdź w pełny ekran")
        else:
            self.fullscreen()
            self.is_fullscreen = True
            button.set_label("Wyjdź z pełnego ekranu")

    def init_audio(self):
        selected_backend = self.backend_combo.get_active_text()
        if selected_backend == "PipeWire":
            pygame.mixer.quit()
            pygame.mixer.init()
            print("Initialized audio with PipeWire")
        elif selected_backend == "JACK":
            os.environ['SDL_AUDIODRIVER'] = 'jack'
            pygame.mixer.quit()
            pygame.mixer.init()
            print("Initialized audio with JACK")

    def play_pattern(self, widget):
        self.init_audio()
        if not self.loop_playing:
            self.loop_playing = True
            self.play_thread = threading.Thread(target=self.loop_play)
            self.play_thread.start()

    def blink_button(self, instrument, step):
        button = self.buttons[instrument][step]
        context = button.get_style_context()
        context.add_class("blink")
        GLib.timeout_add(500, lambda: context.remove_class("blink"))

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
                        modified_sound = self.apply_groove_effects(modified_sound, inst, step_counter)
                        modified_sound.play()
                        GLib.idle_add(self.blink_button, inst, step_counter)

                elapsed_time = time.time() - start_time
                sleep_time = max(0, step_duration - elapsed_time)
                time.sleep(sleep_time)

                step_counter += 1

            self.advance_bpm()

    def stop_pattern(self, widget):
        self.loop_playing = False
        if self.play_thread is not None:
            self.play_thread.join()

    def load_samples(self, widget):
        for inst in self.instruments:
            file_dialog = Gtk.FileChooserDialog(
                title=f"Wybierz sample dla {inst}",
                action=Gtk.FileChooserAction.OPEN,
                buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
            )
            response = file_dialog.run()
            if response == Gtk.ResponseType.OK:
                filename = file_dialog.get_filename()
                self.samples[inst] = filename
                print(f"Loaded sample for {inst}: {filename}")
            file_dialog.destroy()
        self.analyze_sample_volume()

    def analyze_sample_volume(self):
        total_volume = 0
        sample_count = 0

        for instrument, sample_path in self.samples.items():
            if sample_path:
                audio = AudioSegment.from_file(sample_path)
                volume = audio.dBFS
                print(f"{instrument} volume: {volume} dBFS")
                total_volume += volume
                sample_count += 1

        avg_volume = total_volume / sample_count if sample_count > 0 else 0
        print(f"Average sample volume: {avg_volume} dBFS")
        return avg_volume

    def autolevel_samples(self, widget):
        avg_volume = self.analyze_sample_volume()

        for instrument in self.effects:
            normalized_volume = max(min((self.effects[instrument]['volume'] - avg_volume) / 16, 2), -2)
            self.effects[instrument]['volume'] = normalized_volume
            print(f"Adjusted volume for {instrument} to balance levels at {normalized_volume}")
            if instrument in self.effect_sliders and 'volume' in self.effect_sliders[instrument]:
                self.effect_sliders[instrument]['volume'].set_value(normalized_volume)

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
            self.absolute_bpm = project_data.get("absolute_bpm", 120)
            self.dynamic_bpm_list = project_data.get("dynamic_bpm_list", [])
            self.bpm_entry.set_text(str(self.absolute_bpm))
            self.dynamic_bpm_entry.set_text(','.join(map(str, [bpm * 100 / self.absolute_bpm for bpm in self.dynamic_bpm_list])))
            self.update_buttons()
            print(f"Projekt wczytany z: {filename}")

        dialog.destroy()

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
                    midi.addNote(track, 9, self.midi_notes[inst], time, 0.25, 100)
            time += 60 / current_bpm / 4

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

        grid = Gtk.Grid()
        dialog.set_extra_widget(grid)

        style_label = Gtk.Label(label="Style:")
        grid.attach(style_label, 0, 0, 1, 1)
        style_combo = Gtk.ComboBoxText()
        styles = ["Techno", "House", "Drum and Bass", "Ambient", "Trap", "Dubstep"]
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

            midi = MIDIFile(3)
            for i, name in enumerate(["Drums", "Bass", "Lead"]):
                midi.addTrackName(i, 0, name)
            midi.addTempo(0, 0, target_bpm)

            duration = 720
            patterns = self.generate_structured_patterns(style, duration, target_bpm, unique=True)
            self.add_structured_notes(midi, patterns, dynamic_bpm)

            with open(filename, "wb") as output_file:
                midi.writeFile(output_file)
            print(f"Advanced MIDI exported to: {filename}")

        dialog.destroy()

    def generate_structured_patterns(self, style, duration, bpm, unique=False):
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

            intensity = 0.3 if "intro" in section or "outro" in section else 0.7 if "development" in section else 0.5
            drum_pattern = self.adjust_pattern_intensity(drum_pattern, intensity)
            bass_pattern = self.adjust_pattern_intensity(bass_pattern, intensity)
            lead_pattern = self.adjust_pattern_intensity(lead_pattern, intensity)

            patterns[section] = {
                "drums": drum_pattern,
                "bass": bass_pattern,
                "lead": lead_pattern,
                "start_measure": current_measure,
                "duration": section_measures
            }
            current_measure += section_measures

        return patterns

    def adjust_pattern_intensity(self, pattern, intensity):
        if isinstance(pattern, dict):
            for inst in pattern:
                pattern[inst] = [1 if x == 1 and random.random() < intensity else 0 for x in pattern[inst]]
        else:
            pattern = [x if random.random() < intensity else 0 for x in pattern]
        return pattern

    def generate_drum_pattern(self, style, duration, bpm):
        pattern_length = int(duration * bpm / 60 / 4)
        pattern = {inst: [0] * pattern_length for inst in self.instruments}

        if style == "Techno":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 4 == 0 else 0
                pattern['Werbel'][i] = 1 if i % 8 == 4 else 0
                pattern['Talerz'][i] = 1 if i % 4 == 2 and random.random() < 0.3 else 0
                pattern['TomTom'][i] = 1 if i % 16 == 14 and random.random() < 0.3 else 0
        elif style == "House":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 4 in [0, 2] else 0
                pattern['Werbel'][i] = 1 if i % 8 == 4 else 0
                pattern['Talerz'][i] = 1 if i % 8 == 4 and random.random() < 0.25 else 0
                pattern['TomTom'][i] = 1 if i % 16 == 12 else 0
        elif style == "Drum and Bass":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 8 in [0, 3] else 0
                pattern['Werbel'][i] = 1 if i % 8 == 4 else 0
                pattern['Talerz'][i] = 1 if i % 16 == 8 and random.random() < 0.2 else 0
                pattern['TomTom'][i] = 1 if i % 16 == 10 else 0
        elif style == "Ambient":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 16 == 0 else 0
                pattern['Werbel'][i] = 1 if i % 32 == 16 else 0
                pattern['Talerz'][i] = 1 if i % 16 == 8 and random.random() < 0.2 else 0
                pattern['TomTom'][i] = 1 if i % 64 == 48 else 0
        elif style == "Trap":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 8 in [0, 6] else 0
                pattern['Werbel'][i] = 1 if i % 8 == 4 else 0
                pattern['Talerz'][i] = 1 if i % 2 == 0 else 0
                pattern['TomTom'][i] = 1 if i % 16 == 12 else 0
        elif style == "Dubstep":
            for i in range(pattern_length):
                pattern['Stopa'][i] = 1 if i % 8 in [0, 5] else 0
                pattern['Werbel'][i] = 1 if i % 8 == 3 else 0
                pattern['Talerz'][i] = 1 if i % 16 == 8 else 0
                pattern['TomTom'][i] = 1 if i % 16 == 14 else 0

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
        elif style == "Trap":
            for i in range(pattern_length):
                pattern[i] = random.choice([36, 38, 40]) if i % 8 in [0, 4] else 0
        elif style == "Dubstep":
            for i in range(pattern_length):
                pattern[i] = random.choice([36, 38, 41]) if i % 8 in [0, 2] else 0

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
        elif style == "Trap":
            for i in range(pattern_length):
                pattern[i] = random.choice([60, 63, 65]) if i % 8 in [0, 4] else 0
        elif style == "Dubstep":
            for i in range(pattern_length):
                pattern[i] = random.choice([60, 62, 65]) if i % 8 in [0, 3] else 0

        return pattern

    def add_structured_notes(self, midi, structured_patterns, dynamic_bpm):
        time = 0
        current_bpm_index = 0
        steps_per_bpm = 4

        for section, patterns in structured_patterns.items():
            drum_pattern = patterns['drums']
            bass_pattern = patterns['bass']
            lead_pattern = patterns['lead']
            section_duration = patterns['duration'] * 4

            for step in range(section_duration):
                if step % steps_per_bpm == 0:
                    current_bpm = dynamic_bpm[current_bpm_index] * self.absolute_bpm / 100
                    current_bpm_index = (current_bpm_index + 1) % len(dynamic_bpm)

                for inst in self.instruments:
                    if drum_pattern[inst][step % len(drum_pattern[inst])] == 1:
                        midi.addNote(0, 9, self.midi_notes[inst], time, 0.25, 100)

                bass_note = bass_pattern[step % len(bass_pattern)]
                if bass_note != 0:
                    midi.addNote(1, 0, bass_note, time, 0.5, 80)

                lead_note = lead_pattern[step % len(lead_pattern)]
                if lead_note != 0:
                    midi.addNote(2, 1, lead_note, time, 0.25, 90)

                time += 60 / current_bpm / 4

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

        self.randomize_instruments(None)

win = DrumSamplerApp()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
