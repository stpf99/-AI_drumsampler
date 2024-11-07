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
from pydub.utils import mediainfo
from pydub.effects import compress_dynamic_range, low_pass_filter, high_pass_filter, speedup
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
        self.last_button_pressed = None

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(self.main_box)
        self.adjusted_samples = {}
        # Bazowy BPM oraz struktury do przechowywania gęstości patternów
        self.base_bpm = 80
        self.absolute_bpm = 120  # Domyślny BPM
        self.genre_bpm = {"House": 125, "Techno": 130, "Drum and Bass": 165, "Ambient": 80}  # Przykładowe wartości
        self.instruments = ['Talerz', 'Stopa', 'Werbel', 'TomTom']
        self.init_patterns()

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
        self.effects = {inst: {'volume': 0, 'pitch': 0, 'echo': 0, 'reverb': 0, 'pan': 0} for inst in self.instruments}

        self.note_variants = {inst: {'note_type': '1', 'repeats': 1} for inst in self.instruments}

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

                # Add events for scroll and button press
                button.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
                button.connect("toggled", self.on_button_toggled, instrument, step)
                button.connect("scroll-event", self.on_scroll, instrument, step)
                button.connect("button-press-event", self.on_button_press, instrument, step)

                self.grid.attach(button, step + 1, idx + 1, 1, 1)
                self.buttons[instrument].append(button)

        self.loop_playing = False
        self.play_thread = None
        self.absolute_bpm = 120  # Default absolute BPM
        self.dynamic_bpm_list = []
        self.current_bpm_index = 0
        self.steps_per_bpm = 4  # Liczba kroków przed zmianą BPM

        self.effect_sliders = {}  # Dictionary to store volume sliders
        # Add CSS for circular buttons
        self.add_css()


        # Add controls
        self.create_bpm_controls()
        self.create_matched_bpm_control()
        self.create_dynamic_bpm_control()
        self.create_pattern_controls()
        self.create_pattern_length_control()
        self.create_instrument_randomization_controls()
        self.create_preset_selection()
        self.create_autolevel_button()
        self.create_effect_controls()

    def add_css(self):
        css_provider = Gtk.CssProvider()
        css = """
        .circle-red, .circle-green, .circle-blue, .circle-orange {
            border-radius: 15px;
            background-color: white;
            color: black;
        }
        .circle-red:checked { background-color: red; }
        .circle-green:checked { background-color: green; }
        .circle-blue:checked { background-color: blue; }
        .circle-orange:checked { background-color: orange; }
        .blink {
            background-color: yellow;  /* Use a highly visible color */
        }
        """
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )



    def init_patterns(self):
        """Initialize the pattern data structure"""
        self.patterns = {}
        for inst in self.instruments:
            self.patterns[inst] = []
            for _ in range(16):  # 16 steps
                self.patterns[inst].append({
                    'active': False,
                    'note_type': "1",
                    'repeats': 1
                })


    def add_note_controls(self, instrument):
        """Adds dropdowns for note type, double notes, and repeats under each instrument."""
        note_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Note type dropdown with additional double note options
        note_type_combo = Gtk.ComboBoxText()
        for note in ["1", "1/2", "1/4", "1/8", "x2", "x4", "x8", "x16"]:
            note_type_combo.append_text(note)
        note_type_combo.set_active(0)
        note_type_combo.connect("changed", self.on_note_type_changed, instrument)
        note_box.pack_start(note_type_combo, False, False, 0)

        # Repeats dropdown
        repeats_combo = Gtk.ComboBoxText()
        for i in range(1, 9):
            repeats_combo.append_text(str(i))
        repeats_combo.set_active(0)
        repeats_combo.connect("changed", self.on_repeats_changed, instrument)
        note_box.pack_start(repeats_combo, False, False, 0)

        self.main_box.pack_start(note_box, False, False, 0)

    def on_note_type_changed(self, combo, instrument):
        note_type = combo.get_active_text()
        self.note_variants[instrument]['note_type'] = note_type
        self.update_sample_variants(instrument)

    def on_repeats_changed(self, combo, instrument):
        repeats = int(combo.get_active_text())
        self.note_variants[instrument]['repeats'] = repeats
        self.update_sample_variants(instrument)

    def get_adjusted_sample(self, instrument, playback_speed):
        # Load the original sample for the instrument
        original_sample_path = self.samples[instrument]
        original_sample = AudioSegment.from_file(original_sample_path)

        # Adjust playback speed based on the note type
        if playback_speed != 1.0:
            try:
                adjusted_sample = speedup(original_sample, playback_speed, chunk_size=50)
            except Exception as e:
                print(f"Speedup failed for {instrument} with playback speed {playback_speed}: {e}")
                adjusted_sample = original_sample
        else:
            adjusted_sample = original_sample

        return adjusted_sample

    def get_playback_speed(self, note_type):
        playback_speeds = {
            "1": 1.0,
            "1/2": 0.5,
            "1/4": 0.25,
            "1/8": 0.125,
            "x2": 1.0,  # Normal speed for double notes, but repeated
            "x4": 1.0,
            "x8": 1.0,
            "x16": 1.0
        }
        return playback_speeds.get(note_type, 1.0)

    def update_sample_variants(self, instrument):
        """Generate time-stretched or compressed variants for the selected instrument based on note type and repeats."""
        note_type = self.note_variants[instrument]['note_type']
        repeats = self.note_variants[instrument]['repeats']

        # Factor for compressed notes or normal speed for double notes
        sample_duration_factor = {
            "1": 1.0,
            "1/2": 0.5,
            "1/4": 0.25,
            "1/8": 0.125,
            "x2": 1.0,   # Normal speed for double notes, but repeated
            "x4": 1.0,
            "x8": 1.0,
            "x16": 1.0
        }

        playback_speed = sample_duration_factor[note_type]

        # Load the original sample
        original_sample_path = self.samples[instrument]
        original_sample = AudioSegment.from_file(original_sample_path)

        if note_type in {"1", "1/2", "1/4", "1/8"}:
            # For compressed notes, adjust playback speed
            try:
                adjusted_sample = effects.speedup(original_sample, playback_speed, chunk_size=50)
            except Exception as e:
                print(f"Speedup failed for {instrument} with note type '{note_type}': {e}")
                # For very short samples, repeat instead of speedup as a fallback
                adjusted_sample = original_sample * int(1 / playback_speed)
        elif note_type in {"x2", "x4", "x8", "x16"}:
            # For double notes, repeat sample according to the note type
            repeat_count = int(note_type[1:])  # Extract the repeat number (2, 4, 8, 16)
            adjusted_sample = original_sample * repeat_count

        # Store adjusted sample in memory
        self.adjusted_samples[instrument] = adjusted_sample
        print(f"Stored adjusted sample for {instrument}, note type: '{note_type}', repeats: {repeats}")

    def autofill_pattern(self):
        """
        Intelligently fill pattern based on existing steps using musical rules and probabilities
        that create more natural rhythmic patterns.
        """
        try:
            pattern_length = int(self.length_spinbutton.get_value())
            genre = self.preset_genre_combo.get_active_text()

            # Genre-specific rhythm densities (probability of activating a step)
            genre_densities = {
                "Techno": 0.7,
                "House": 0.5,
                "Drum and Bass": 0.8,
                "Ambient": 0.3
            }

            # Instrument-specific rules
            instrument_rules = {
                "kick": {"offbeat_prob": 0.2, "consecutive_prob": 0.1},
                "snare": {"offbeat_prob": 0.8, "consecutive_prob": 0.05},
                "hihat": {"offbeat_prob": 0.6, "consecutive_prob": 0.4},
                "perc": {"offbeat_prob": 0.4, "consecutive_prob": 0.3}
            }

            base_density = genre_densities.get(genre, 0.5)

            for instrument, steps in self.patterns.items():
                # Get instrument-specific rules
                rules = instrument_rules.get(instrument,
                                          {"offbeat_prob": 0.3, "consecutive_prob": 0.2})

                # Find currently active steps
                active_steps = [i for i, step in enumerate(steps)
                              if isinstance(step, dict) and step.get('active')]

                # Process each step
                for i in range(pattern_length):
                    if i not in active_steps:
                        # Calculate position-based probability
                        is_downbeat = i % 4 == 0
                        is_offbeat = i % 2 == 1

                        # Base probability adjusted by position
                        prob = base_density
                        if is_downbeat:
                            prob *= 1.5  # Increase probability on downbeats
                        elif is_offbeat:
                            prob *= rules["offbeat_prob"]

                        # Check for consecutive hits
                        prev_active = i > 0 and isinstance(steps[i-1], dict) and steps[i-1].get('active')
                        if prev_active:
                            prob *= rules["consecutive_prob"]

                        # Activate step based on calculated probability
                        if random.random() < prob:
                            # Choose appropriate note type based on position
                            if is_downbeat:
                                note_type = random.choice(["1", "1/2"])
                            elif is_offbeat:
                                note_type = random.choice(["1/4", "1/8"])
                            else:
                                note_type = random.choice(["1/4", "1/2", "1/8"])

                            self.patterns[instrument][i] = {
                                'active': True,
                                'note_type': note_type,
                                'repeats': random.randint(1, 2)
                            }
                        else:
                            self.patterns[instrument][i] = {
                                'active': False,
                                'note_type': "1",
                                'repeats': 1
                            }

            # Update the UI
            self.update_buttons()
            print("Pattern autofill completed with musical rules")

        except Exception as e:
            print(f"Error in autofill_pattern: {e}")

    def create_pattern_controls(self):
        # Main horizontal box for all controls
        genre_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(genre_box, False, False, 0)

        # Predefined genres dropdown section
        preset_label = Gtk.Label(label="FX Genre:")
        genre_box.pack_start(preset_label, False, False, 0)

        self.preset_genre_combo = Gtk.ComboBoxText()
        genres = ["House", "Techno", "Drum and Bass", "Ambient"]
        for genre in genres:
            self.preset_genre_combo.append_text(genre)
        self.preset_genre_combo.set_active(0)
        genre_box.pack_start(self.preset_genre_combo, False, False, 0)

        # Auto FX Style button
        auto_fx_button = Gtk.Button(label="Auto FX Style")
        auto_fx_button.connect("clicked", self.apply_auto_fx_for_selected_style)
        genre_box.pack_start(auto_fx_button, False, False, 0)

        # Add some spacing between the two sections
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        genre_box.pack_start(separator, False, False, 10)

        # Custom genre input section
        custom_label = Gtk.Label(label="Custom Genre:")
        genre_box.pack_start(custom_label, False, False, 0)

        self.custom_genre_entry = Gtk.Entry()
        genre_box.pack_start(self.custom_genre_entry, False, False, 0)

        # Generate button
        generate_button = Gtk.Button(label="Generate Pattern")
        generate_button.connect("clicked", self.generate_ai_pattern)
        genre_box.pack_start(generate_button, False, False, 0)

        # Show all elements
        genre_box.show_all()

    def create_grid(self):
        """Create the grid of buttons"""
        grid = Gtk.Grid()
        grid.set_row_spacing(4)
        grid.set_column_spacing(4)

        # Create buttons for each instrument and step
        for i, instrument in enumerate(self.instruments):
            for step in range(16):
                button = Gtk.ToggleButton()
                button.set_size_request(50, 50)

                # Connect signals
                button.connect("toggled", self.on_button_toggled, instrument, step)
                button.connect("scroll-event", self.on_scroll, instrument, step)

                grid.attach(button, step, i, 1, 1)

        return grid

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
        """Handle button toggle with individual step settings"""
        try:
            is_active = button.get_active()

            # Ensure the patterns structure exists
            if instrument not in self.patterns:
                self.patterns[instrument] = []
            if len(self.patterns[instrument]) <= step:
                while len(self.patterns[instrument]) <= step:
                    self.patterns[instrument].append({
                        'active': False,
                        'note_type': "1",
                        'repeats': 1
                    })

            # Ensure we have a dictionary at this position
            if not isinstance(self.patterns[instrument][step], dict):
                self.patterns[instrument][step] = {
                    'active': False,
                    'note_type': "1",
                    'repeats': 1
                }

            # Update the active state
            self.patterns[instrument][step]['active'] = is_active

            # Update button visual
            if is_active:
                self.update_button_visual(button, instrument, step)
            else:
                button.set_label("")

        except Exception as e:
            print(f"Error in on_button_toggled: {e}")
            print(f"Instrument: {instrument}, Step: {step}")
            print(f"Current pattern state: {self.patterns.get(instrument, [])}")

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

    def update_buttons(self):
        """Update all button visuals to match current pattern state"""
        pattern_length = int(self.length_spinbutton.get_value())

        for inst in self.instruments:
            for i in range(pattern_length):
                try:
                    step_data = self.patterns[inst][i]
                    button = self.buttons[inst][i]

                    # Ensure step_data is a dictionary
                    if not isinstance(step_data, dict):
                        step_data = {
                            'active': bool(step_data),  # Convert old format to new
                            'note_type': "1",
                            'repeats': 1
                        }
                        self.patterns[inst][i] = step_data

                    # Update button state
                    button.set_active(step_data['active'])

                    # Update visual if active
                    if step_data['active']:
                        self.update_button_visual(button, inst, i)
                    else:
                        button.set_label("")

                except Exception as e:
                    print(f"Error updating button {inst}[{i}]: {e}")

    def update_button_visual(self, button, instrument, step):
        """Update button appearance based on step settings"""
        try:
            if not isinstance(self.patterns[instrument][step], dict):
                self.patterns[instrument][step] = {
                    'active': False,
                    'note_type': "1",
                    'repeats': 1
                }

            step_data = self.patterns[instrument][step]

            if step_data['active']:
                # Set button label
                button.set_label(f"{step_data['note_type']}\n×{step_data['repeats']}")

                # Update button styling
                context = button.get_style_context()

                # Remove previous classes
                for class_name in ["note-type-1", "note-type-1-2", "note-type-1-4", "note-type-1-8"]:
                    context.remove_class(class_name)

                # Add new class
                note_class = f"note-type-{step_data['note_type'].replace('/', '-')}"
                context.add_class(note_class)
            else:
                button.set_label("")

            button.queue_draw()

        except Exception as e:
            print(f"Error in update_button_visual: {e}")
            print(f"Instrument: {instrument}, Step: {step}")
            print(f"Current pattern state: {self.patterns.get(instrument, [])}")

    def on_button_press(self, widget, event, instrument, step):
        # Store the last button pressed (1 for left, 3 for right)
        self.last_button_pressed = event.button

    def on_scroll(self, widget, event, instrument, step):
        """Handle scroll events for step modification"""
        # Ensure we're working with a dictionary
        if not isinstance(self.patterns[instrument][step], dict):
            print(f"Error: Invalid pattern data at instrument {instrument}, step {step}")
            return

        # Check if the step is active
        if not self.patterns[instrument][step]['active']:
            return

        scroll_direction = event.direction

        # Determine action based on the last button pressed
        if self.last_button_pressed == 1:  # Left-click adjusts note type
            current_type = self.patterns[instrument][step]['note_type']
            new_type = self.adjust_note_type(current_type, scroll_direction)
            self.patterns[instrument][step]['note_type'] = new_type
        elif self.last_button_pressed == 3:  # Right-click adjusts repeats
            current_repeats = self.patterns[instrument][step]['repeats']
            new_repeats = max(1, min(8, current_repeats + (1 if scroll_direction == Gdk.ScrollDirection.UP else -1)))
            self.patterns[instrument][step]['repeats'] = new_repeats

        # Update the button visual
        self.update_button_visual(widget, instrument, step)

    def adjust_note_type(self, current_type, scroll_direction):
        note_types = ["1", "1/2", "1/4", "1/8", "x2", "x4", "x8", "x16"]
        index = note_types.index(current_type)
        if scroll_direction == Gdk.ScrollDirection.UP:
            index = (index + 1) % len(note_types)
        else:
            index = (index - 1) % len(note_types)
        return note_types[index]

    def create_toolbar(self):
        toolbar = Gtk.Toolbar()
        self.main_box.pack_start(toolbar, False, False, 0)

        # Informacje o przyciskach i ich funkcjach
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

        # Dodawanie przycisków na podstawie `button_info`
        for icon_name, callback, tooltip in button_info:
            button = Gtk.ToolButton()
            button.set_icon_name(icon_name)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", callback)
            toolbar.insert(button, -1)

        # Tworzenie menu wyboru backendu audio
        audio_backend_label = Gtk.Label(label="Audio Backend:")
        toolbar.insert(Gtk.ToolItem(), -1)  # Wstawienie spacji przed menu
        audio_backend_item = Gtk.ToolItem()
        backend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        self.backend_combo = Gtk.ComboBoxText()
        self.backend_combo.append_text("PipeWire")
        self.backend_combo.append_text("JACK")
        self.backend_combo.set_active(0)  # Ustawienie PipeWire jako domyślnego

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
        """Calculate the density of the pattern based on active steps"""
        try:
            total_steps = len(self.instruments) * 16  # Total possible steps
            total_active_steps = 0

            # Count active steps across all instruments
            for instrument in self.patterns:
                for step in self.patterns[instrument]:
                    if isinstance(step, dict) and step.get('active'):
                        # Add weight based on repeats
                        repeats = step.get('repeats', 1)
                        total_active_steps += repeats

            # Calculate density as a ratio of active steps to total possible steps
            density = total_active_steps / total_steps if total_steps > 0 else 0
            print(f"Pattern density calculated: {density:.2f}")
            return density

        except Exception as e:
            print(f"Error calculating pattern density: {e}")
            return 0.5  # Return default density on error

    def matched_bpm(self, widget):
        """Adjust BPM based on pattern density relative to base BPM."""
        try:
            density = self.calculate_pattern_density()
            # Scale BPM between base_bpm - 40 and base_bpm + 40 based on density
            new_bpm = self.base_bpm + (density - 0.5) * 80
            self.absolute_bpm = int(max(30, min(300, new_bpm)))  # Clamp between 30 and 300 BPM
            self.bpm_entry.set_text(str(self.absolute_bpm))
            print(f"Matched BPM set to: {self.absolute_bpm}")
        except Exception as e:
            print(f"Error in matched_bpm: {e}")
            # Fallback to base BPM
            self.absolute_bpm = self.base_bpm
            self.bpm_entry.set_text(str(self.absolute_bpm))

    def perfect_tempo_bpm(self, widget):
        """Adjust BPM to average genre tempo after matched_bpm calculation."""
        try:
            self.matched_bpm(widget)  # First run matched BPM
            genre = self.custom_genre_entry.get_text()
            avg_bpm = self.genre_bpm.get(genre, self.base_bpm)

            # Calculate average between matched BPM and genre BPM
            self.absolute_bpm = int((self.absolute_bpm + avg_bpm) / 2)

            # Clamp the result between reasonable BPM values
            self.absolute_bpm = max(30, min(300, self.absolute_bpm))

            self.bpm_entry.set_text(str(self.absolute_bpm))
            print(f"Perfect Tempo BPM set to: {self.absolute_bpm}")
        except Exception as e:
            print(f"Error in perfect_tempo_bpm: {e}")
            # Fallback to base BPM
            self.absolute_bpm = self.base_bpm
            self.bpm_entry.set_text(str(self.absolute_bpm))


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
        self.absolute_bpm = max(5, self.absolute_bpm - 5)  # Limit minimum BPM to 60
        self.bpm_entry.set_text(str(self.absolute_bpm))
        self.update_dynamic_bpm()

    def randomize_pattern(self, widget):
        pattern_length = int(self.length_spinbutton.get_value())

        # Generowanie losowego wzorca od zera
        for inst in self.instruments:
            self.patterns[inst] = []  # Inicjalizujemy wzorzec dla każdego instrumentu od zera

            for i in range(pattern_length):
                if inst == 'Stopa':
                    # Wzorzec losowy dla stopy
                    step = {
                        'active': random.choice([True, False]) if i % 4 == 0 else False,
                        'note_type': random.choice(["1", "1/2", "1/4", "1/8"]),
                        'repeats': random.randint(1, 2)
                    }
                elif inst == 'Werbel':
                    # Wzorzec dla werbla
                    step = {
                        'active': i % 4 == 2,
                        'note_type': random.choice(["1", "1/2"]),
                        'repeats': 1
                    }
                elif inst == 'Talerz':
                    # Losowy wzorzec dla talerza, niezależny od stopy
                    step = {
                        'active': random.choice([True, False]),
                        'note_type': random.choice(["1/2", "1/4", "1/8"]),
                        'repeats': random.randint(1, 2)
                    }
                elif inst == 'TomTom':
                    # Wzorzec dla TomTom
                    step = {
                        'active': random.choice([True, False]) if i % 8 == 7 else False,
                        'note_type': random.choice(["1", "1/4"]),
                        'repeats': random.randint(1, 2)
                    }

                # Dodajemy krok do wzorca dla bieżącego instrumentu
                self.patterns[inst].append(step)

        # Dodatkowa losowa zmiana instrumentów po wygenerowaniu wzorca
        self.randomize_instruments(None)
        self.update_buttons()  # Aktualizacja przycisków w GUI


    def create_instrument_randomization_controls(self):
        randomize_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(randomize_box, False, False, 0)

        # Etykieta informacyjna dla sekcji
        randomize_label = Gtk.Label(label="Instrument Randomization:")
        randomize_box.pack_start(randomize_label, False, False, 0)

        # Pole do ustawienia prawdopodobieństwa randomizacji
        self.randomize_probability_adjustment = Gtk.Adjustment(value=10, lower=0, upper=100, step_increment=1)
        self.randomize_probability_spin = Gtk.SpinButton()
        self.randomize_probability_spin.set_adjustment(self.randomize_probability_adjustment)
        self.randomize_probability_spin.set_value(10)
        randomize_box.pack_start(self.randomize_probability_spin, False, False, 0)

        # Przycisk do losowego uzupełniania instrumentów
        randomize_button = Gtk.Button(label="Randomize Instruments")
        randomize_button.connect("clicked", self.randomize_instruments)
        randomize_box.pack_start(randomize_button, False, False, 0)

        # Nowy przycisk "Autofill" do automatycznego uzupełniania wzorca
        autofill_button = Gtk.Button(label="Autofill")
        autofill_button.connect("clicked", lambda widget: self.autofill_pattern())
        randomize_box.pack_start(autofill_button, False, False, 0)


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
        """Rozpocznij odtwarzanie patternu z dynamicznymi efektami."""
        # Inicjalizacja wybranego backendu audio
        self.init_audio()

        # Sprawdzenie, czy odtwarzanie już trwa; jeśli nie, uruchom nowy wątek
        if not self.loop_playing:
            self.loop_playing = True
            # Uruchomienie wątku, który wywoła funkcję `loop_play`
            self.play_thread = threading.Thread(target=self.loop_play)
            self.play_thread.start()

    def blink_button(self, instrument, step):
        button = self.buttons[instrument][step]
        context = button.get_style_context()
        context.add_class("blink")  # Add blink effect

        # Remove the blink effect after 200 milliseconds
        GLib.timeout_add(100, lambda: context.remove_class("blink"))


    def stop_pattern(self, widget):
        self.loop_playing = False
        if self.play_thread is not None:
            self.play_thread.join()

    def load_project(self, widget):
        # Create the file chooser dialog
        dialog = Gtk.FileChooserDialog(
            title="Load Project", parent=self, action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)

        # Run the dialog and get the response
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            try:
                with open(filename, 'r') as f:
                    project_data = json.load(f)

                # Load patterns, ensuring the format matches the expected structure
                if "patterns" in project_data:
                    self.patterns = project_data["patterns"]
                else:
                    print("Warning: 'patterns' key missing in project file. Initializing empty patterns.")
                    self.init_patterns()

                # Load samples, ensuring paths are valid
                if "samples" in project_data:
                    self.samples = project_data["samples"]
                    for inst, sample_path in self.samples.items():
                        if os.path.exists(sample_path):
                            print(f"Loaded sample for {inst}: {sample_path}")
                        else:
                            print(f"Warning: Sample file for {inst} not found at {sample_path}.")
                            self.samples[inst] = None
                else:
                    print("Warning: 'samples' key missing in project file.")
                    self.samples = {}

                # Load BPM and dynamic BPM list with default fallbacks
                self.absolute_bpm = project_data.get("absolute_bpm", 120)
                self.dynamic_bpm_list = project_data.get("dynamic_bpm_list", [100])

                # Load note variants
                self.note_variants = project_data.get("note_variants", {})

                # Update the UI components
                self.bpm_entry.set_text(str(self.absolute_bpm))
                self.update_buttons()  # Update button visuals to reflect loaded pattern
                print(f"Project loaded from: {filename}")

            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading project file: {e}")

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

        effects = ['Volume', 'Pitch', 'Echo', 'Reverb', 'Pan']
        for col, effect in enumerate(effects, start=1):
            label = Gtk.Label(label=effect)
            effect_grid.attach(label, col, 0, 1, 1)

        for row, instrument in enumerate(self.instruments, start=1):
            label = Gtk.Label(label=instrument)
            effect_grid.attach(label, 0, row, 1, 1)
            self.effect_sliders[instrument] = {}  # Initialize sliders for each instrument

            for col, effect in enumerate(effects, start=1):
                adjustment = Gtk.Adjustment(value=0, lower=-2, upper=2, step_increment=0.1)
                slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
                slider.set_digits(1)
                slider.connect('value-changed', self.on_effect_changed, instrument, effect.lower())
                effect_grid.attach(slider, col, row, 1, 1)


                # Create and attach reset button for each effect
                reset_button = Gtk.Button(label="Reset")
                reset_button.set_size_request(60, 35)  # Adjust size to fit well next to slider
                reset_button.connect('clicked', self.reset_effect, slider, instrument, effect.lower())
                effect_grid.attach(reset_button, col + len(effects), row, 1, 1)  # Place the reset button next to the slider

                # Store volume sliders for Auto Level updates
                if effect.lower() == 'volume':
                    self.effect_sliders[instrument]['volume'] = slider

    def create_autolevel_button(self):
        autolevel_button = Gtk.Button(label="Auto Level")
        autolevel_button.connect("clicked", self.autolevel_samples)
        self.main_box.pack_start(autolevel_button, False, False, 0)

    def load_samples(self, widget):
        for inst in self.instruments:
            file_dialog = Gtk.FileChooserDialog(
                title=f"Wybierz sample dla {inst}",
                action=Gtk.FileChooserAction.OPEN
            )
            file_dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)

            response = file_dialog.run()
            if response == Gtk.ResponseType.OK:
                filename = file_dialog.get_filename()
                # Wczytaj próbkę jako obiekt dźwiękowy
                self.samples[inst] = filename  # Save filename instead of pygame.mixer.Sound object
                print(f"Loaded sample for {inst}: {filename}")
            file_dialog.destroy()
        self.analyze_sample_volume()

    def analyze_sample_volume(self):
        total_volume = 0
        sample_count = 0

        for instrument, sample_path in self.samples.items():
            if sample_path:
                audio = AudioSegment.from_file(self.samples[instrument])
                volume = audio.dBFS  # Get volume in dBFS
                print(f"{instrument} volume: {volume} dBFS")
                total_volume += volume
                sample_count += 1

        avg_volume = total_volume / sample_count if sample_count > 0 else 0
        print(f"Average sample volume: {avg_volume} dBFS")
        return avg_volume

    def autolevel_samples(self, widget):
        """Adjust volumes of samples to a balanced average."""
        avg_volume = self.analyze_sample_volume()

        for instrument, settings in self.effects.items():
            normalized_volume = max(min((settings['volume'] - avg_volume) / 16, 2), -2)
            settings['volume'] = normalized_volume

            if instrument in self.effect_sliders:
                self.effect_sliders[instrument]['volume'].set_value(normalized_volume)
            print(f"Normalized volume for {instrument} to {normalized_volume}")

    def on_effect_changed(self, slider, instrument, effect):
        value = slider.get_value()
        self.effects[instrument][effect] = value
        print(f"Changed {effect} for {instrument} to {value}")

    def apply_auto_fx_for_style(self, style):
        fx_settings = {
            "Techno": {'volume': 0.5, 'pitch': 0, 'echo': 1, 'reverb': 1, 'pan': 0},
            "House": {'volume': 0.3, 'pitch': 0, 'echo': 0.5, 'reverb': 1, 'pan': 0.1},
            "Drum and Bass": {'volume': 1.0, 'pitch': -1, 'echo': 1, 'reverb': 0.8, 'pan': -0.1},
            "Ambient": {'volume': 0, 'pitch': 0, 'echo': 0.8, 'reverb': 1, 'pan': 0.2}
        }
        settings = fx_settings.get(style, {})
        for instrument in self.instruments:
            for effect, value in settings.items():
                self.effects[instrument][effect] = value
                print(f"{instrument} {effect} set to {value} for {style}")
                if effect in self.effect_sliders[instrument]:
                    self.effect_sliders[instrument][effect].set_value(value)  # Update the slider i

    def apply_auto_fx_for_selected_style(self, widget):
        selected_style = self.preset_genre_combo.get_active_text()
        if selected_style:
            # Apply effect settings for the selected style
            self.apply_auto_fx_for_style(selected_style)
            print(f"Applied auto FX for style: {selected_style}")

    def reset_effect(self, button, slider, instrument, effect):
        slider.set_value(0)  # Reset the slider to 0
        self.effects[instrument][effect] = 0
        print(f"Reset {effect} for {instrument} to 0")
        # Ensure the GUI slider is also updated
        if effect in self.effect_sliders[instrument]:
            self.effect_sliders[instrument][effect].set_value(0)  # Update the GUI slider

    def save_project(self, widget):
        dialog = Gtk.FileChooserDialog(title="Save Project", parent=self, action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)

        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            project_data = {
                "patterns": self.patterns,
                "samples": self.samples,
                "absolute_bpm": self.absolute_bpm,
                "dynamic_bpm_list": self.dynamic_bpm_list,
                "note_variants": self.note_variants
            }
            with open(filename, 'w') as f:
                json.dump(project_data, f)
            print(f"Project saved as: {filename}")

        dialog.destroy()

    def on_effect_changed(self, slider, instrument, effect):
        value = slider.get_value()
        self.effects[instrument][effect] = value
        print(f"Changed {effect} for {instrument} to {value}")

    def apply_effects(self, sound, instrument):
        """Apply audio effects to the sound dynamically."""
        effects = self.effects[instrument]

        try:
            # Jeśli sound jest ścieżką, załaduj go jako obiekt Sound
            if isinstance(sound, str):
                sound = pygame.mixer.Sound(sound)

            # Konwertuj dźwięk do formatu numpy dla przetwarzania
            sound_array = pygame.sndarray.array(sound).astype(np.float32) / 32767.0
            if sound_array.ndim < 2:
                sound_array = sound_array.mean(axis=2)
            # Zastosowanie głośności
            volume_factor = 10 ** (effects['volume'] / 20.0)  # Konwersja dB na współczynnik liniowy
            sound_array *= volume_factor

            # Przetwarzanie wysokości dźwięku
            if effects['pitch'] != 0:
                pitch_factor = 2 ** (effects['pitch'] / 12.0)
                new_length = int(len(sound_array) / pitch_factor)
                indices = np.linspace(0, len(sound_array) - 1, new_length)
                sound_array = np.interp(indices, np.arange(len(sound_array)), sound_array)

            # Efekt echa
            if effects['echo'] > 0:
                echo_delay = int(44100 * 0.25)  # 250ms delay
                echo_strength = effects['echo']
                echo_array = np.zeros_like(sound_array)
                echo_array[echo_delay:] = sound_array[:-echo_delay] * echo_strength
                sound_array += echo_array

            # Efekt pogłosu
            if effects['reverb'] > 0:
                reverb_length = int(44100 * 0.1)
                impulse_response = np.exp(-np.linspace(0, 4, reverb_length))
                sound_array = np.convolve(sound_array, impulse_response * effects['reverb'], mode='same')

            # Efekt panoramy
            if effects['pan'] != 0 and sound_array.ndim == 2:
                pan = effects['pan']
                left_factor = np.sqrt(0.5 - pan / 2)
                right_factor = np.sqrt(0.5 + pan / 2)
                sound_array[:, 0] *= left_factor
                sound_array[:, 1] *= right_factor


            # Clipping i konwersja z powrotem do Sound
            sound_array = np.clip(sound_array, -1.0, 1.0)
            sound_array = (sound_array * 32767).astype(np.int16)
            return pygame.sndarray.make_sound(sound_array)

        except Exception as e:
            print(f"Error applying effects to {instrument}: {e}")
            return sound  # Zwrot oryginalnego obiektu dźwiękowego
            print(f"{instrument} sound array shape: {sound_array.shape}")

    def loop_play(self):
        """Main playback loop with blinking effect for the current step."""
        try:
            pattern_length = int(self.length_spinbutton.get_value())
            step_counter = 0

            while self.loop_playing:
                current_bpm = self.get_next_bpm()
                base_step_duration = 60 / current_bpm / 4  # Base time per step in seconds

                for _ in range(self.steps_per_bpm):
                    if step_counter >= pattern_length:
                        step_counter = 0  # Reset the counter if it exceeds pattern length

                    start_time = time.time()

                    for inst in self.instruments:
                        step_data = self.patterns[inst][step_counter]

                        if step_data['active']:
                            original_sample = self.samples[inst]
                            sample_with_fx = self.apply_effects(original_sample, inst)
                            playback_speed = self.get_playback_speed(step_data['note_type'])
                            adjusted_step_duration = base_step_duration * playback_speed

                            for _ in range(step_data['repeats']):
                                sample_with_fx.play()
                                time.sleep(adjusted_step_duration / step_data['repeats'])

                            # Trigger the blinking effect
                            GLib.idle_add(self.blink_button, inst, step_counter)

                    elapsed_time = time.time() - start_time
                    remaining_time = base_step_duration - elapsed_time
                    if remaining_time > 0:
                        time.sleep(remaining_time)

                    step_counter += 1
                    self.advance_bpm()

        except Exception as e:
            print(f"Error in loop_play: {e}")
            self.loop_playing = False

    def export_to_midi(self, widget):
        try:
            dialog = Gtk.FileChooserDialog(title="Export MIDI", parent=self, action=Gtk.FileChooserAction.SAVE)
            dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
            dialog.set_current_name("drum_pattern.mid")
            response = dialog.run()

            if response == Gtk.ResponseType.OK:
                filename = dialog.get_filename()
                midi = MIDIFile(1)
                midi.addTempo(0, 0, self.absolute_bpm)

                for instrument, steps in self.patterns.items():
                    for i, step in enumerate(steps):
                        if step['active']:
                            duration = self.get_note_duration_factor(step['note_type']) * (1 / step['repeats'])
                            midi.addNote(0, 9, self.midi_notes[instrument], i * duration, duration, 100)

                with open(filename, 'wb') as output_file:
                    midi.writeFile(output_file)
                print(f"MIDI file exported to: {filename}")

            dialog.destroy()

        except Exception as e:
            print(f"Error exporting to MIDI: {e}")

    def get_note_duration_factor(self, note_type):
        """Return duration factor based on note type"""
        duration_factors = {
            "1": 1.0,
            "1/2": 0.5,
            "1/4": 0.25,
            "1/8": 0.125,
            "x2": 0.5,  # For double notes, each note takes half the step time
            "x4": 0.25,
            "x8": 0.125,
            "x16": 0.0625
        }
        return duration_factors.get(note_type, 1.0)

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
        genre = self.custom_genre_entry.get_text()

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
