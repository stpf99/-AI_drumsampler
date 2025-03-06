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
        self.scale_factor = 1.0  # Initial scale factor

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
        self.advanced_sequencer_mode = False
        self.simple_patterns = {inst: [0] * 16 for inst in self.instruments}
        self.advanced_patterns = {inst: [{'active': False, 'note_type': '1', 'repeats': 1} for _ in range(16)] for inst in self.instruments}
        self.patterns = self.simple_patterns
        self.colors = ['red', 'green', 'blue', 'orange']
        self.midi_notes = {'Talerz': 49, 'Stopa': 36, 'Werbel': 38, 'TomTom': 45}
        self.buttons = {}
        self.samples = {}
        self.effects = {inst: {'volume': 0, 'pitch': 0, 'echo': 0, 'reverb': 0, 'pan': 0} for inst in self.instruments}
        self.last_button_pressed = None

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
                button.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
                button.connect("toggled", self.on_button_toggled, instrument, step)
                button.connect("scroll-event", self.on_scroll, instrument, step)
                button.connect("button-press-event", self.on_button_press, instrument, step)
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
        self.create_sample_manipulation_area()

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

        sequencer_mode_label = Gtk.Label(label="Sequencer Mode:")
        toolbar.insert(Gtk.ToolItem(), -1)
        sequencer_mode_item = Gtk.ToolItem()
        sequencer_mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.sequencer_mode_switch = Gtk.Switch()
        self.sequencer_mode_switch.set_active(False)
        self.sequencer_mode_switch.connect("notify::active", self.on_sequencer_mode_switch)
        sequencer_mode_label_mode = Gtk.Label(label="Simple | Advanced")
        sequencer_mode_box.pack_start(sequencer_mode_label, False, False, 0)
        sequencer_mode_box.pack_start(self.sequencer_mode_switch, False, False, 5)
        sequencer_mode_box.pack_start(sequencer_mode_label_mode, False, False, 0)
        sequencer_mode_item.add(sequencer_mode_box)
        toolbar.insert(sequencer_mode_item, -1)

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

    def create_matched_bpm_control(self):
        bpm_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(bpm_box, False, False, 0)

        matched_bpm_button = Gtk.Button(label="Matched BPM")
        matched_bpm_button.connect("clicked", self.matched_bpm)
        bpm_box.pack_start(matched_bpm_button, False, False, 0)

        perfect_bpm_button = Gtk.Button(label="Perfect Tempo BPM")
        perfect_bpm_button.connect("clicked", self.perfect_tempo_bpm)
        bpm_box.pack_start(perfect_bpm_button, False, False, 0)

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

    def create_pattern_controls(self):
        genre_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(genre_box, False, False, 0)
    
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
    
        reset_fx_button = Gtk.Button(label="Reset Genre FX")
        reset_fx_button.connect("clicked", self.reset_genre_fx)
        genre_box.pack_start(reset_fx_button, False, False, 0)
    
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        genre_box.pack_start(separator, False, False, 10)
    
        custom_label = Gtk.Label(label="Custom Genre:")
        genre_box.pack_start(custom_label, False, False, 0)
    
        self.custom_genre_entry = Gtk.Entry()
        genre_box.pack_start(self.custom_genre_entry, False, False, 0)
    
        progression_label = Gtk.Label(label="Progression:")
        genre_box.pack_start(progression_label, False, False, 0)
        self.progression_combo = Gtk.ComboBoxText()
        progressions = ["Linear", "Dense", "Sparse", "Random"]
        for p in progressions:
            self.progression_combo.append_text(p)
        self.progression_combo.set_active(0)
        genre_box.pack_start(self.progression_combo, False, False, 0)
    
        mod_label = Gtk.Label(label="Mod:")
        genre_box.pack_start(mod_label, False, False, 0)
        self.mod_combo = Gtk.ComboBoxText()
        mods = ["None", "Simplify", "More Complex"]
        for m in mods:
            self.mod_combo.append_text(m)
        self.mod_combo.set_active(0)
        genre_box.pack_start(self.mod_combo, False, False, 0)
    
        occurrences_label = Gtk.Label(label="Occurrences:")
        genre_box.pack_start(occurrences_label, False, False, 0)
        self.occurrences_spin = Gtk.SpinButton()
        self.occurrences_spin.set_adjustment(Gtk.Adjustment(value=4, lower=1, upper=16, step_increment=1))
        genre_box.pack_start(self.occurrences_spin, False, False, 0)
    
        intensity_label = Gtk.Label(label="Intensity:")
        genre_box.pack_start(intensity_label, False, False, 0)
        self.intensity_spin = Gtk.SpinButton()
        self.intensity_spin.set_adjustment(Gtk.Adjustment(value=0.5, lower=0, upper=1, step_increment=0.1))
        self.intensity_spin.set_numeric(True)
        self.intensity_spin.set_digits(1)
        genre_box.pack_start(self.intensity_spin, False, False, 0)
    
        generate_button = Gtk.Button(label="Generate Pattern")
        generate_button.connect("clicked", self.generate_custom_pattern)
        genre_box.pack_start(generate_button, False, False, 0)
    
        genre_box.show_all()

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
                adjustment = Gtk.Adjustment(value=0, lower=-5, upper=5, step_increment=0.1)
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

        reset_all_button = Gtk.Button(label="Reset All Effects")
        reset_all_button.connect("clicked", self.reset_all_effects)
        effect_box.pack_start(reset_all_button, False, False, 0)

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

        reset_groove_button = Gtk.Button(label="Reset Groove")
        reset_groove_button.connect("clicked", self.reset_groove)
        groove_box.pack_start(reset_groove_button, False, False, 0)

    def create_drummer_to_audio_button(self):
        drummer_button = Gtk.Button(label="Add Drummer to Audio")
        drummer_button.connect("clicked", self.add_drummer_to_audio)
        self.main_box.pack_start(drummer_button, False, False, 0)

    def create_sample_manipulation_area(self):
        sample_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=int(10 * self.scale_factor))
        sample_box.set_hexpand(True)
        self.main_box.pack_start(sample_box, False, False, int(10 * self.scale_factor))

        self.nominal_adsr = {
            'Talerz': {'attack': 0.01, 'decay': 0.1, 'sustain': 0.8, 'release': 0.6},
            'Stopa': {'attack': 0.01, 'decay': 0.2, 'sustain': 0.3, 'release': 0.1},
            'Werbel': {'attack': 0.02, 'decay': 0.2, 'sustain': 0.4, 'release': 0.3},
            'TomTom': {'attack': 0.03, 'decay': 0.3, 'sustain': 0.5, 'release': 0.4}
        }
        self.current_adsr = {inst: self.nominal_adsr[inst].copy() for inst in self.instruments}
        self.preview_active = {inst: False for inst in self.instruments}

        self.adsr_entries = {}
        for inst in self.instruments:
            inst_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=int(5 * self.scale_factor))
            inst_label = Gtk.Label(label=inst)
            inst_box.pack_start(inst_label, False, False, 0)

            adsr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=int(5 * self.scale_factor))
            self.adsr_entries[inst] = {}
            for param in ['attack', 'decay', 'sustain', 'release']:
                param_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=int(2 * self.scale_factor))
                minus_btn = Gtk.Button(label="-")
                minus_btn.set_size_request(int(20 * self.scale_factor), int(20 * self.scale_factor))
                minus_btn.connect("clicked", self.adjust_adsr, inst, param, -0.1)
                param_box.pack_start(minus_btn, False, False, 0)

                entry = Gtk.Entry()
                entry.set_width_chars(int(4 * self.scale_factor))
                entry.set_text(f"{self.current_adsr[inst][param]:.2f}")
                entry.connect("changed", self.on_adsr_entry_changed, inst, param)
                param_box.pack_start(entry, False, False, 0)
                self.adsr_entries[inst][param] = entry

                plus_btn = Gtk.Button(label="+")
                plus_btn.set_size_request(int(20 * self.scale_factor), int(20 * self.scale_factor))
                plus_btn.connect("clicked", self.adjust_adsr, inst, param, 0.1)
                param_box.pack_start(plus_btn, False, False, 0)

                adsr_box.pack_start(param_box, False, False, 0)

            inst_box.pack_start(adsr_box, False, False, 0)

            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=int(5 * self.scale_factor))
            reset_btn = Gtk.Button(label="R")
            reset_btn.set_size_request(int(20 * self.scale_factor), int(20 * self.scale_factor))
            reset_btn.connect("clicked", self.reset_adsr, inst)
            btn_box.pack_start(reset_btn, False, False, 0)

            rand_btn = Gtk.Button(label="?")
            rand_btn.set_size_request(int(20 * self.scale_factor), int(20 * self.scale_factor))
            rand_btn.connect("clicked", self.randomize_adsr, inst)
            btn_box.pack_start(rand_btn, False, False, 0)

            preview_check = Gtk.CheckButton()
            preview_check.connect("toggled", self.toggle_preview, inst)
            btn_box.pack_start(preview_check, False, False, 0)
            inst_box.pack_start(btn_box, False, False, 0)

            sample_box.pack_start(inst_box, False, False, 0)

        bank_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=int(5 * self.scale_factor))
        bank_label = Gtk.Label(label="Bank:")
        bank_box.pack_start(bank_label, False, False, 0)

        self.bank_combo = Gtk.ComboBoxText()
        self.bank_combo.append_text("Default")
        self.bank_combo.set_active(0)
        bank_box.pack_start(self.bank_combo, False, False, 0)

        load_btn = Gtk.Button(label="L")
        load_btn.set_size_request(int(20 * self.scale_factor), int(20 * self.scale_factor))
        load_btn.connect("clicked", self.load_sample_bank)
        bank_box.pack_start(load_btn, False, False, 0)

        export_btn = Gtk.Button(label="E")
        export_btn.set_size_request(int(20 * self.scale_factor), int(20 * self.scale_factor))
        export_btn.connect("clicked", self.export_sample_bank)
        bank_box.pack_start(export_btn, False, False, 0)

        sample_box.pack_end(bank_box, False, False, 0)

        if not self.samples:
            self.generate_default_samples()

    def scale_interface(self, widget, allocation):
        width, height = allocation.width, allocation.height
        self.scale_factor = min(width / 1280, height / 720)

        button_size = int(30 * self.scale_factor)
        for row in self.buttons.values():
            for button in row:
                button.set_size_request(button_size, button_size)

        self.grid.set_row_spacing(int(6 * self.scale_factor))
        self.grid.set_column_spacing(int(6 * self.scale_factor))
        self.main_box.set_spacing(int(6 * self.scale_factor))

        if hasattr(self, 'adsr_entries'):
            for inst in self.instruments:
                for param, entry in self.adsr_entries[inst].items():
                    entry.set_width_chars(int(4 * self.scale_factor))
                for child in self.main_box.get_children()[-1].get_children():
                    if isinstance(child, Gtk.Box):
                        for subchild in child.get_children():
                            if isinstance(subchild, Gtk.Button):
                                subchild.set_size_request(int(20 * self.scale_factor), int(20 * self.scale_factor))

    # Event Handlers and Helper Methods
    def on_button_toggled(self, button, instrument, step):
        if self.advanced_sequencer_mode:
            is_active = button.get_active()
            step_data = self.patterns[instrument][step]
            step_data['active'] = is_active
            if is_active and step_data['note_type'] == '1' and step_data['repeats'] == 1:
                step_data['note_type'] = '1'
                step_data['repeats'] = 1
            self.update_button_visual(button, instrument, step)
        else:
            self.patterns[instrument][step] = int(button.get_active())

    def update_buttons(self):
        pattern_length = int(self.length_spinbutton.get_value())
        for inst in self.instruments:
            if self.advanced_sequencer_mode:
                if len(self.patterns[inst]) < pattern_length:
                    self.patterns[inst].extend([{'active': False, 'note_type': '1', 'repeats': 1} for _ in range(pattern_length - len(self.patterns[inst]))])
                elif len(self.patterns[inst]) > pattern_length:
                    self.patterns[inst] = self.patterns[inst][:pattern_length]
            else:
                if len(self.patterns[inst]) < pattern_length:
                    self.patterns[inst].extend([0] * (pattern_length - len(self.patterns[inst])))
                elif len(self.patterns[inst]) > pattern_length:
                    self.patterns[inst] = self.patterns[inst][:pattern_length]
    
        for inst in self.instruments:
            for i in range(pattern_length):
                try:
                    button = self.buttons[inst][i]
                    if self.advanced_sequencer_mode:
                        step_data = self.patterns[inst][i]
                        button.set_active(step_data['active'])
                        self.update_button_visual(button, inst, i)
                    else:
                        button.set_active(bool(self.patterns[inst][i]))
                        button.set_label("")
                except IndexError:
                    self.reinitialize_buttons()
                    return
        self.grid.queue_draw()

    def update_button_visual(self, button, instrument, step):
        if self.advanced_sequencer_mode:
            step_data = self.patterns[instrument][step]
            if step_data['active']:
                button.set_label(f"{step_data['note_type']}\n×{step_data['repeats']}")
            else:
                button.set_label("")
        else:
            button.set_label("")

    def reinitialize_buttons(self):
        pattern_length = int(self.length_spinbutton.get_value())
        for inst in self.instruments:
            self.buttons[inst] = []
            for i in range(pattern_length):
                button = Gtk.ToggleButton()
                button.set_size_request(30, 30)
                context = button.get_style_context()
                context.add_class(f"circle-{self.colors[self.instruments.index(inst)]}")
                button.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
                button.connect("toggled", self.on_button_toggled, inst, i)
                button.connect("scroll-event", self.on_scroll, inst, i)
                button.connect("button-press-event", self.on_button_press, inst, i)
                self.grid.attach(button, i + 1, self.instruments.index(inst) + 1, 1, 1)
                self.buttons[inst].append(button)
        self.grid.show_all()
        self.update_buttons()

    def on_button_press(self, widget, event, instrument, step):
        self.last_button_pressed = event.button

    def on_scroll(self, widget, event, instrument, step):
        if not self.advanced_sequencer_mode or not self.patterns[instrument][step]['active']:
            return
        scroll_direction = event.direction
        step_data = self.patterns[instrument][step]
        if self.last_button_pressed == 1:
            current_type = step_data['note_type']
            new_type = self.adjust_note_type(current_type, scroll_direction)
            step_data['note_type'] = new_type
        elif self.last_button_pressed == 3:
            current_repeats = step_data['repeats']
            new_repeats = max(1, min(8, current_repeats + (1 if scroll_direction == Gdk.ScrollDirection.UP else -1)))
            step_data['repeats'] = new_repeats
        self.update_button_visual(widget, instrument, step)

    def adjust_note_type(self, current_type, scroll_direction):
        note_types = ["1", "1/2", "1/4", "1/8", "x2", "x4", "x8", "x16"]
        index = note_types.index(current_type)
        if scroll_direction == Gdk.ScrollDirection.UP:
            index = (index + 1) % len(note_types)
        else:
            index = (index - 1) % len(note_types)
        return note_types[index]

    def on_sequencer_mode_switch(self, switch, gparam):
        self.advanced_sequencer_mode = switch.get_active()
        self.patterns = self.advanced_patterns if self.advanced_sequencer_mode else self.simple_patterns
        self.update_buttons()

    def bpm_step_up(self, widget):
        self.absolute_bpm = min(300, self.absolute_bpm + 5)
        self.bpm_entry.set_text(str(self.absolute_bpm))
        self.update_dynamic_bpm()

    def bpm_step_down(self, widget):
        self.absolute_bpm = max(60, self.absolute_bpm - 5)
        self.bpm_entry.set_text(str(self.absolute_bpm))
        self.update_dynamic_bpm()

    def calculate_pattern_density(self):
        total_active_steps = 0
        total_steps = len(self.instruments) * len(self.patterns[self.instruments[0]])
        if self.advanced_sequencer_mode:
            for inst in self.instruments:
                for step in self.patterns[inst]:
                    if step['active']:
                        total_active_steps += step['repeats']
        else:
            for inst in self.instruments:
                total_active_steps += sum(self.patterns[inst])
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

    def apply_dynamic_bpm(self, widget):
        bpm_string = self.dynamic_bpm_entry.get_text()
        try:
            percentages = [float(bpm.strip()) for bpm in bpm_string.split(',')]
            self.dynamic_bpm_list = [self.absolute_bpm * (p / 100) for p in percentages]
            self.current_bpm_index = 0
        except ValueError:
            print("Invalid BPM input.")

    def update_dynamic_bpm(self):
        if self.dynamic_bpm_list:
            percentages = [float(bpm.strip()) for bpm in self.dynamic_bpm_entry.get_text().split(',')]
            self.dynamic_bpm_list = [self.absolute_bpm * (p / 100) for p in percentages]

    def get_next_bpm(self):
        if not self.dynamic_bpm_list:
            return self.absolute_bpm
        current_bpm = self.dynamic_bpm_list[self.current_bpm_index]
        return current_bpm

    def advance_bpm(self):
        if self.dynamic_bpm_list:
            self.current_bpm_index = (self.current_bpm_index + 1) % len(self.dynamic_bpm_list)

    def generate_custom_pattern(self, widget):
        genre = self.custom_genre_entry.get_text() or "Generic"
        progression = self.progression_combo.get_active_text()
        occurrences = int(self.occurrences_spin.get_value())
        intensity = self.intensity_spin.get_value()
        pattern_length = int(self.length_spinbutton.get_value())
        mod = self.mod_combo.get_active_text()
    
        if self.advanced_sequencer_mode:
            for inst in self.instruments:
                self.patterns[inst] = [{'active': False, 'note_type': '1', 'repeats': 1} for _ in range(pattern_length)]
        else:
            for inst in self.instruments:
                self.patterns[inst] = [0] * pattern_length
    
        if progression == "Linear":
            for inst in self.instruments:
                step_interval = pattern_length // occurrences
                for i in range(0, pattern_length, step_interval):
                    if random.random() < intensity:
                        self._apply_step(inst, i, genre)
        elif progression == "Dense":
            for inst in self.instruments:
                for i in range(pattern_length):
                    if random.random() < intensity * 0.8:
                        self._apply_step(inst, i, genre)
        elif progression == "Sparse":
            for inst in self.instruments:
                for i in range(pattern_length):
                    if random.random() < intensity * 0.3:
                        self._apply_step(inst, i, genre)
        elif progression == "Random":
            for inst in self.instruments:
                for i in range(pattern_length):
                    if random.random() < intensity:
                        self._apply_step(inst, i, genre)
    
        if mod == "Simplify":
            for inst in self.instruments:
                for i in range(pattern_length):
                    if self.advanced_sequencer_mode:
                        if self.patterns[inst][i]['active'] and random.random() < 0.5:
                            self.patterns[inst][i]['active'] = False
                    else:
                        if self.patterns[inst][i] == 1 and random.random() < 0.5:
                            self.patterns[inst][i] = 0
        elif mod == "More Complex":
            for inst in self.instruments:
                for i in range(pattern_length):
                    if random.random() < intensity * 0.2:
                        self._apply_step(inst, i, genre, complex=True)
                        
        for inst in self.instruments:
            for i in range(pattern_length):
                if inst == 'Stopa':
                    self.patterns[inst][i] = 1 if i % 4 == 0 and random.random() < intensity else 0
                elif inst == 'Werbel':
                    self.patterns[inst][i] = 1 if i % 4 == 2 else 0
                elif inst == 'Talerz':
                    self.patterns[inst][i] = random.choice([0, 1]) if self.patterns['Stopa'][i] == 0 else 0
                elif inst == 'TomTom':
                    self.patterns[inst][i] = random.choice([0, 1]) if i % 8 == 7 else 0
    
                self.update_buttons()

    def _apply_step(self, inst, step, genre, complex=False):
        genre_rules = {
            "Techno": {"Stopa": ["1"], "Werbel": ["1/2"], "Talerz": ["1/4"], "TomTom": ["1/8"]},
            "House": {"Stopa": ["1"], "Werbel": ["1"], "Talerz": ["1/2"], "TomTom": ["1/4"]},
            "Drum and Bass": {"Stopa": ["1/4"], "Werbel": ["1/8"], "Talerz": ["1/8"], "TomTom": ["1/16"]},
            "Ambient": {"Stopa": ["1"], "Werbel": ["1/2"], "Talerz": ["1/4"], "TomTom": ["1/2"]},
            "Trap": {"Stopa": ["1/4"], "Werbel": ["1/8"], "Talerz": ["x2"], "TomTom": ["1/8"]},
            "Dubstep": {"Stopa": ["1/2"], "Werbel": ["1/4"], "Talerz": ["1/8"], "TomTom": ["1/16"]},
            "Jazz": {"Stopa": ["1/2"], "Werbel": ["1/4"], "Talerz": ["1/2"], "TomTom": ["1"]},
            "Breakbeat": {"Stopa": ["1/4"], "Werbel": ["1/8"], "Talerz": ["1/4"], "TomTom": ["1/8"]}
        }
        rules = genre_rules.get(genre, {"Stopa": ["1"], "Werbel": ["1"], "Talerz": ["1"], "TomTom": ["1"]})
    
        if self.advanced_sequencer_mode:
            self.patterns[inst][step]['active'] = True
            self.patterns[inst][step]['note_type'] = random.choice(rules[inst])
            self.patterns[inst][step]['repeats'] = random.randint(2, 4) if complex else random.randint(1, 2)
        else:
            self.patterns[inst][step] = 1

    def on_pattern_length_changed(self, spinbutton):
        new_length = int(spinbutton.get_value())
        current_length = len(self.patterns[self.instruments[0]])

        for instrument in self.instruments:
            if new_length > current_length:
                if self.advanced_sequencer_mode:
                    self.patterns[instrument].extend([{'active': False, 'note_type': '1', 'repeats': 1} for _ in range(new_length - current_length)])
                else:
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
        genre = self.custom_genre_entry.get_text() or self.preset_genre_combo.get_active_text() or "Generic"
        progression = self.progression_combo.get_active_text()
        intensity = self.intensity_spin.get_value()
        occurrences = int(self.occurrences_spin.get_value())
        mod = self.mod_combo.get_active_text()
    
        for instrument in self.instruments:
            if self.advanced_sequencer_mode:
                active_steps = [i for i, step in enumerate(self.patterns[instrument]) if step['active']]
                for i in range(pattern_length):
                    if i not in active_steps:
                        self._generate_advanced_pattern(instrument, pattern_length, genre, progression, intensity, occurrences, mod)
                # Dodajemy podstawowe reguły dla gatunku
                if instrument == 'Stopa' and i % 4 == 0:
                    self.patterns[instrument][i]['active'] = True
                elif instrument == 'Werbel' and i % 8 == 4:
                    self.patterns[instrument][i]['active'] = True
            else:
                active_steps = [i for i, step in enumerate(self.patterns[instrument]) if step == 1]
                for i in range(pattern_length):
                    if i not in active_steps:
                        self._generate_simple_pattern(instrument, pattern_length, genre, progression, intensity, occurrences, mod)
                # Dodajemy podstawowe reguły dla gatunku
                if instrument == 'Stopa' and i % 4 == 0:
                    self.patterns[instrument][i] = 1
                elif instrument == 'Werbel' and i % 8 == 4:
                    self.patterns[instrument][i] = 1
    
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
            if self.advanced_sequencer_mode:
                self.patterns['Stopa'][i]['active'] = True if i % 4 == 0 else False
                self.patterns['Werbel'][i]['active'] = True if i % 8 == 4 else False
                self.patterns['Talerz'][i]['active'] = True if i % 4 == 2 else False
                self.patterns['TomTom'][i]['active'] = True if i % 16 == 14 else False
            else:
                self.patterns['Stopa'][i] = 1 if i % 4 == 0 else 0
                self.patterns['Werbel'][i] = 1 if i % 8 == 4 else 0
                self.patterns['Talerz'][i] = 1 if i % 4 == 2 else 0
                self.patterns['TomTom'][i] = 1 if i % 16 == 14 else 0

    def generate_minimal_techno(self):
        pattern_length = int(self.length_spinbutton.get_value())
        for i in range(pattern_length):
            if self.advanced_sequencer_mode:
                self.patterns['Stopa'][i]['active'] = True if i % 4 == 0 or i % 16 == 14 else False
                self.patterns['Werbel'][i]['active'] = True if i % 8 == 4 else False
                self.patterns['Talerz'][i]['active'] = True if i % 2 == 0 else False
                self.patterns['TomTom'][i]['active'] = True if i % 16 == 10 else False
            else:
                self.patterns['Stopa'][i] = 1 if i % 4 == 0 or i % 16 == 14 else 0
                self.patterns['Werbel'][i] = 1 if i % 8 == 4 else 0
                self.patterns['Talerz'][i] = 1 if i % 2 == 0 else 0
                self.patterns['TomTom'][i] = 1 if i % 16 == 10 else 0

    def generate_hard_techno(self):
        pattern_length = int(self.length_spinbutton.get_value())
        for i in range(pattern_length):
            if self.advanced_sequencer_mode:
                self.patterns['Stopa'][i]['active'] = True if i % 2 == 0 else False
                self.patterns['Werbel'][i]['active'] = True if i % 8 == 4 or i % 8 == 6 else False
                self.patterns['Talerz'][i]['active'] = True if i % 4 == 0 else False
                self.patterns['TomTom'][i]['active'] = True if i % 8 == 7 else False
            else:
                self.patterns['Stopa'][i] = 1 if i % 2 == 0 else 0
                self.patterns['Werbel'][i] = 1 if i % 8 == 4 or i % 8 == 6 else 0
                self.patterns['Talerz'][i] = 1 if i % 4 == 0 else 0
                self.patterns['TomTom'][i] = 1 if i % 8 == 7 else 0

    def on_effect_changed(self, slider, instrument, effect):
        value = slider.get_value()
        self.effects[instrument][effect] = value

    def reset_effect(self, button, slider, instrument, effect):
        slider.set_value(0)
        self.effects[instrument][effect] = 0

    def reset_all_effects(self, widget):
        for instrument in self.instruments:
            for effect in self.effects[instrument]:
                self.effects[instrument][effect] = 0
                if effect in self.effect_sliders[instrument]:
                    self.effect_sliders[instrument][effect].set_value(0)

    def reset_genre_fx(self, widget):
        for instrument in self.instruments:
            for effect in self.effects[instrument]:
                self.effects[instrument][effect] = 0
                if effect in self.effect_sliders[instrument]:
                    self.effect_sliders[instrument][effect].set_value(0)

    def apply_effects(self, sound, instrument):
        sound = self.apply_adsr_to_sound(sound, instrument)
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

    def apply_adsr_to_sound(self, sound, instrument):
        sound_array = pygame.sndarray.array(sound)
        sample_rate = 44100
        total_samples = len(sound_array)
        adsr = self.current_adsr[instrument]
        is_stereo = sound_array.ndim == 2
    
        # Handle stereo or mono input
        if is_stereo:
            channels = sound_array.shape[1]  # Number of channels (usually 2)
        else:
            channels = 1
            sound_array = sound_array.reshape(-1, 1)  # Convert mono to 2D for consistency
    
        # Calculate segment lengths
        attack_samples = int(adsr['attack'] * sample_rate)
        decay_samples = int(adsr['decay'] * sample_rate)
        release_samples = int(adsr['release'] * sample_rate)
        sustain_samples = total_samples - attack_samples - decay_samples - release_samples
    
        # Adjust if sustain_samples is negative
        if sustain_samples < 0:
            excess = -sustain_samples
            total_adsr = attack_samples + decay_samples + release_samples
            scale_factor = (total_samples - excess) / total_adsr
            attack_samples = int(attack_samples * scale_factor)
            decay_samples = int(decay_samples * scale_factor)
            release_samples = int(release_samples * scale_factor)
            sustain_samples = total_samples - attack_samples - decay_samples - release_samples
    
        # Create envelope (1D)
        envelope = np.zeros(total_samples, dtype=np.float32)
        if attack_samples > 0:
            envelope[:attack_samples] = np.linspace(0, 1, min(attack_samples, total_samples))
        if decay_samples > 0 and attack_samples < total_samples:
            decay_end = min(attack_samples + decay_samples, total_samples)
            envelope[attack_samples:decay_end] = np.linspace(1, adsr['sustain'], decay_end - attack_samples)
        if sustain_samples > 0 and attack_samples + decay_samples < total_samples:
            sustain_end = min(attack_samples + decay_samples + sustain_samples, total_samples)
            envelope[attack_samples + decay_samples:sustain_end] = adsr['sustain']
        if release_samples > 0 and total_samples - release_samples > 0:
            release_start = max(0, total_samples - release_samples)
            envelope[release_start:] = np.linspace(adsr['sustain'], 0, total_samples - release_start)
    
        # Apply envelope to each channel
        if is_stereo:
            sound_array[:, 0] = sound_array[:, 0] * envelope  # Left channel
            sound_array[:, 1] = sound_array[:, 1] * envelope  # Right channel
        else:
            sound_array[:, 0] = sound_array[:, 0] * envelope  # Mono channel
            sound_array = np.hstack((sound_array, sound_array))  # Duplicate mono to stereo
    
        return pygame.sndarray.make_sound(sound_array.astype(np.int16))
        
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

    def apply_groove(self, widget):
        self.groove_type = self.groove_combo.get_active_text()
        self.play_pattern(widget)

    def reset_groove(self, widget):
        self.groove_type = 'simple'
        self.groove_combo.set_active(0)

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
            sound.play()
        return sound

    def apply_stretch_groove(self, sound, instrument, step):
        stretched_bpm = self.get_next_bpm() * random.uniform(0.9, 1.1)
        self.advance_bpm()
        return sound

    def apply_echoes_groove(self, sound, instrument, step):
        return self.apply_effects_with_echo(sound, instrument)

    def apply_bouncy_groove(self, sound, instrument, step):
        volume_factor = random.choice([0.8, 1.2])
        sound.set_volume(volume_factor)
        return sound

    def apply_relax_groove(self, sound, instrument, step):
        return self.apply_effects_with_echo(sound, instrument)

    def apply_effects_with_echo(self, sound, instrument):
        effect_sound = pygame.mixer.Sound(self.samples[instrument])
        effect_sound.play(maxtime=500)
        return sound

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
                tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)

                update_progress(0.3, "Detecting rhythmic patterns...")
                segments = librosa.effects.split(y, top_db=30)
                if len(segments) < 2:
                    raise ValueError("Not enough segments found for processing.")

                update_progress(0.5, "Generating percussion track...")
                percussion_track, original_audio, sr = self.advanced_generate_drum_track(audio_path, tempo, beat_frames)

                update_progress(0.7, "Synthesizing audio...")
                percussion_audio = self.synthesize_percussion_audio(percussion_track, sr, original_audio, tempo)

                update_progress(0.9, "Saving tracks...")
                self.save_generated_tracks(audio_path, percussion_track, original_audio, sr, tempo)

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

    def advanced_generate_drum_track(self, audio_path, tempo, beat_frames):
        y, sr = librosa.load(audio_path, sr=22050)
        total_duration = librosa.get_duration(y=y, sr=sr)
        
        steps_per_beat = 1
        beats_per_second = tempo / 60
        total_steps = int(total_duration * beats_per_second * steps_per_beat)

        percussion_track = {inst: [0] * total_steps for inst in self.instruments}

        beat_steps = [int(frame * steps_per_beat * beats_per_second * sr / 22050) for frame in beat_frames]

        for i in range(total_steps):
            if i in beat_steps:
                percussion_track['Stopa'][i] = 1 if i % (steps_per_beat * 1) == 0 else 0
                percussion_track['Werbel'][i] = 1 if i % (steps_per_beat * 1) == steps_per_beat * 2 else 0
            if random.random() < 0.3:
                percussion_track['Talerz'][i] = 1
            if i % (steps_per_beat * 2) == steps_per_beat * 7 and random.random() < 0.2:
                percussion_track['TomTom'][i] = 1

        return percussion_track, y, sr

    def synthesize_percussion_audio(self, percussion_track, sr, original_audio, tempo):
        beats_per_second = tempo / 60
        steps_per_beat = 4
        step_duration = int(sr / (beats_per_second * steps_per_beat))
        total_length = len(percussion_track['Stopa'])

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
                    if end <= len(audio):
                        audio[start:end] += sample_array
                except Exception as e:
                    print(f"Error processing {inst} sample: {e}")

        original_rms = np.sqrt(np.mean(original_audio**2))
        percussion_rms = np.sqrt(np.mean(audio**2))
        if percussion_rms > 0:
            scaling_factor = original_rms / percussion_rms
            audio *= scaling_factor

        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio /= max_val

        return audio

    def save_generated_tracks(self, audio_path, percussion_track, original_audio, sr, tempo):
        percussion_audio = self.synthesize_percussion_audio(percussion_track, sr, original_audio, tempo)
        max_length = len(original_audio)
        percussion_audio = librosa.util.fix_length(percussion_audio, size=max_length)
        combined_audio = (original_audio * 0.4 + percussion_audio * 0.5)
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
        elif selected_backend == "JACK":
            os.environ['SDL_AUDIODRIVER'] = 'jack'
            pygame.mixer.quit()
            pygame.mixer.init()

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
            base_step_duration = 60 / current_bpm / 4

            for _ in range(self.steps_per_bpm):
                if step_counter >= pattern_length:
                    step_counter = 0

                start_time = time.time()

                for inst in self.instruments:
                    if self.advanced_sequencer_mode:
                        step_data = self.patterns[inst][step_counter]
                        if step_data['active'] and inst in self.samples:
                            original_sound = pygame.mixer.Sound(self.samples[inst])
                            modified_sound = self.apply_effects(original_sound, inst)
                            playback_speed = self.get_playback_speed(step_data['note_type'])
                            adjusted_duration = base_step_duration * playback_speed
                            for _ in range(step_data['repeats']):
                                modified_sound.play()
                                time.sleep(adjusted_duration / step_data['repeats'])
                            GLib.idle_add(self.blink_button, inst, step_counter)
                    else:
                        if self.patterns[inst][step_counter] == 1 and inst in self.samples:
                            original_sound = pygame.mixer.Sound(self.samples[inst])
                            modified_sound = self.apply_effects(original_sound, inst)
                            modified_sound = self.apply_groove_effects(modified_sound, inst, step_counter)
                            modified_sound.play()
                            GLib.idle_add(self.blink_button, inst, step_counter)

                elapsed_time = time.time() - start_time
                sleep_time = max(0, base_step_duration - elapsed_time)
                time.sleep(sleep_time)

                step_counter += 1
            self.advance_bpm()

    def get_playback_speed(self, note_type):
        playback_speeds = {
            "1": 1.0, "1/2": 0.5, "1/4": 0.25, "1/8": 0.125,
            "x2": 1.0, "x4": 1.0, "x8": 1.0, "x16": 1.0
        }
        return playback_speeds.get(note_type, 1.0)

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
                total_volume += volume
                sample_count += 1

        avg_volume = total_volume / sample_count if sample_count > 0 else 0
        return avg_volume

    def autolevel_samples(self, widget):
        avg_volume = self.analyze_sample_volume()
        for instrument in self.effects:
            normalized_volume = max(min((self.effects[instrument]['volume'] - avg_volume) / 16, 5), -5)
            self.effects[instrument]['volume'] = normalized_volume
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
                "simple_patterns": self.simple_patterns,
                "advanced_patterns": self.advanced_patterns,
                "advanced_sequencer_mode": self.advanced_sequencer_mode,
                "samples": self.samples,
                "absolute_bpm": self.absolute_bpm,
                "dynamic_bpm_list": self.dynamic_bpm_list
            }

            with open(filename, 'w') as f:
                json.dump(project_data, f)

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

            self.simple_patterns = project_data.get("simple_patterns", {inst: [0] * 16 for inst in self.instruments})
            self.advanced_patterns = project_data.get("advanced_patterns", {inst: [{'active': False, 'note_type': '1', 'repeats': 1} for _ in range(16)] for inst in self.instruments})
            self.advanced_sequencer_mode = project_data.get("advanced_sequencer_mode", False)
            self.patterns = self.advanced_patterns if self.advanced_sequencer_mode else self.simple_patterns
            self.sequencer_mode_switch.set_active(self.advanced_sequencer_mode)
            self.samples = project_data["samples"]
            self.absolute_bpm = project_data.get("absolute_bpm", 120)
            self.dynamic_bpm_list = project_data.get("dynamic_bpm_list", [])
            self.bpm_entry.set_text(str(self.absolute_bpm))
            self.dynamic_bpm_entry.set_text(','.join(map(str, [bpm * 100 / self.absolute_bpm for bpm in self.dynamic_bpm_list])))
            self.update_buttons()

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
            step_duration = 60 / current_bpm / 4

            for inst in self.instruments:
                if self.advanced_sequencer_mode:
                    step_data = self.patterns[inst][step]
                    if step_data['active']:
                        duration = step_duration * self.get_playback_speed(step_data['note_type']) / step_data['repeats']
                        for _ in range(step_data['repeats']):
                            midi.addNote(track, 9, self.midi_notes[inst], time, duration, 100)
                            time += duration
                else:
                    if self.patterns[inst][step] == 1:
                        midi.addNote(track, 9, self.midi_notes[inst], time, 0.25, 100)
            if not self.advanced_sequencer_mode:
                time += step_duration

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
            if self.advanced_sequencer_mode:
                for i in range(pattern_length):
                    if inst == 'Stopa':
                        self.patterns[inst][i]['active'] = random.choice([True, False]) if i % 4 == 0 else False
                        self.patterns[inst][i]['note_type'] = random.choice(["1", "1/2", "1/4", "1/8"])
                        self.patterns[inst][i]['repeats'] = random.randint(1, 2)
                    elif inst == 'Werbel':
                        self.patterns[inst][i]['active'] = True if i % 4 == 2 else False
                        self.patterns[inst][i]['note_type'] = random.choice(["1", "1/2"])
                        self.patterns[inst][i]['repeats'] = 1
                    elif inst == 'Talerz':
                        self.patterns[inst][i]['active'] = random.choice([True, False]) if not self.patterns['Stopa'][i]['active'] else False
                        self.patterns[inst][i]['note_type'] = random.choice(["1/2", "1/4", "1/8"])
                        self.patterns[inst][i]['repeats'] = random.randint(1, 2)
                    elif inst == 'TomTom':
                        self.patterns[inst][i]['active'] = random.choice([True, False]) if i % 8 == 7 else False
                        self.patterns[inst][i]['note_type'] = random.choice(["1", "1/4"])
                        self.patterns[inst][i]['repeats'] = random.randint(1, 2)
            else:
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


    def _generate_advanced_pattern(self, instrument, pattern_length, genre, progression, intensity, occurrences, mod):
        step_interval = pattern_length // occurrences
        genre_rules = {
            "Techno": {"Stopa": ["1"], "Werbel": ["1/2"], "Talerz": ["1/4"], "TomTom": ["1/8"]},
            "House": {"Stopa": ["1"], "Werbel": ["1"], "Talerz": ["1/2"], "TomTom": ["1/4"]},
            "Drum and Bass": {"Stopa": ["1/4"], "Werbel": ["1/8"], "Talerz": ["1/8"], "TomTom": ["1/16"]},
            "Ambient": {"Stopa": ["1"], "Werbel": ["1/2"], "Talerz": ["1/4"], "TomTom": ["1/2"]},
            "Trap": {"Stopa": ["1/4"], "Werbel": ["1/8"], "Talerz": ["x2"], "TomTom": ["1/8"]},
            "Dubstep": {"Stopa": ["1/2"], "Werbel": ["1/4"], "Talerz": ["1/8"], "TomTom": ["1/16"]},
            "Jazz": {"Stopa": ["1/2"], "Werbel": ["1/4"], "Talerz": ["1/2"], "TomTom": ["1"]},
            "Breakbeat": {"Stopa": ["1/4"], "Werbel": ["1/8"], "Talerz": ["1/4"], "TomTom": ["1/8"]}
        }
        rules = genre_rules.get(genre, {"Stopa": ["1"], "Werbel": ["1"], "Talerz": ["1"], "TomTom": ["1"]})
    
        if progression == "Linear":
            for i in range(0, pattern_length, step_interval):
                if random.random() < intensity:
                    self.patterns[instrument][i]['active'] = True
                    self.patterns[instrument][i]['note_type'] = random.choice(rules[instrument])
                    self.patterns[instrument][i]['repeats'] = 1 if mod == "Simplify" else random.randint(1, 2)
        elif progression == "Dense":
            for i in range(pattern_length):
                if random.random() < intensity * 0.8:
                    self.patterns[instrument][i]['active'] = True
                    self.patterns[instrument][i]['note_type'] = random.choice(rules[instrument])
                    self.patterns[instrument][i]['repeats'] = 2 if mod == "More Complex" else 1
        elif progression == "Sparse":
            for i in range(pattern_length):
                if random.random() < intensity * 0.3:
                    self.patterns[instrument][i]['active'] = True
                    self.patterns[instrument][i]['note_type'] = random.choice(rules[instrument])
                    self.patterns[instrument][i]['repeats'] = 1
        elif progression == "Random":
            for i in range(pattern_length):
                if random.random() < intensity:
                    self.patterns[instrument][i]['active'] = True
                    self.patterns[instrument][i]['note_type'] = random.choice(rules[instrument])
                    self.patterns[instrument][i]['repeats'] = random.randint(1, 3) if mod == "More Complex" else 1
    
        if mod == "Simplify":
            for i in range(pattern_length):
                if self.patterns[instrument][i]['active'] and random.random() < 0.5:
                    self.patterns[instrument][i]['active'] = False
        elif mod == "More Complex":
            for i in range(pattern_length):
                if random.random() < intensity * 0.2:
                    self.patterns[instrument][i]['active'] = True
                    self.patterns[instrument][i]['note_type'] = random.choice(rules[instrument])
                    self.patterns[instrument][i]['repeats'] = random.randint(2, 4)
    
    def _generate_simple_pattern(self, instrument, pattern_length, genre, progression, intensity, occurrences, mod):
        step_interval = pattern_length // occurrences
        if progression == "Linear":
            for i in range(0, pattern_length, step_interval):
                if random.random() < intensity:
                    self.patterns[instrument][i] = 1
        elif progression == "Dense":
            for i in range(pattern_length):
                if random.random() < intensity * 0.8:
                    self.patterns[instrument][i] = 1
        elif progression == "Sparse":
            for i in range(pattern_length):
                if random.random() < intensity * 0.3:
                    self.patterns[instrument][i] = 1
        elif progression == "Random":
            for i in range(pattern_length):
                if random.random() < intensity:
                    self.patterns[instrument][i] = 1
    
        if mod == "Simplify":
            for i in range(pattern_length):
                if self.patterns[instrument][i] == 1 and random.random() < 0.5:
                    self.patterns[instrument][i] = 0
        elif mod == "More Complex":
            for i in range(pattern_length):
                if random.random() < intensity * 0.2:
                    self.patterns[instrument][i] = 1



    # Sample Manipulation Handlers
    def on_adsr_entry_changed(self, entry, instrument, param):
        try:
            value = float(entry.get_text())
            self.current_adsr[instrument][param] = max(0.0, min(value, 1.0 if param == 'sustain' else 5.0))
            entry.set_text(f"{self.current_adsr[instrument][param]:.2f}")
            if self.preview_active[instrument]:
                self.preview_sample(instrument)
        except ValueError:
            entry.set_text(f"{self.current_adsr[instrument][param]:.2f}")

    def adjust_adsr(self, button, instrument, param, step):
        current_value = self.current_adsr[instrument][param]
        new_value = max(0.0, min(current_value + step, 1.0 if param == 'sustain' else 5.0))
        self.current_adsr[instrument][param] = new_value
        self.adsr_entries[instrument][param].set_text(f"{new_value:.2f}")
        if self.preview_active[instrument]:
            self.preview_sample(instrument)

    def reset_adsr(self, button, instrument):
        self.current_adsr[instrument] = self.nominal_adsr[instrument].copy()
        for param, entry in self.adsr_entries[instrument].items():
            entry.set_text(f"{self.current_adsr[instrument][param]:.2f}")
        if self.preview_active[instrument]:
            self.preview_sample(instrument)

    def randomize_adsr(self, button, instrument):
        for param in ['attack', 'decay', 'sustain', 'release']:
            if param == 'sustain':
                self.current_adsr[instrument][param] = random.uniform(0.1, 1.0)
            else:
                self.current_adsr[instrument][param] = random.uniform(0.01, 2.0)
            self.adsr_entries[instrument][param].set_text(f"{self.current_adsr[instrument][param]:.2f}")
        if self.preview_active[instrument]:
            self.preview_sample(instrument)

    def toggle_preview(self, checkbutton, instrument):
        self.preview_active[instrument] = checkbutton.get_active()
        if self.preview_active[instrument]:
            self.preview_sample(instrument)

    def preview_sample(self, instrument):
        if instrument in self.samples:
            sound = pygame.mixer.Sound(self.samples[instrument])
            sound = self.apply_effects(sound, instrument)
            sound.play()

    def generate_default_samples(self):
        sample_rate = 44100
        duration = 0.5
        for inst in self.instruments:
            if inst not in self.samples:
                t = np.linspace(0, duration, int(sample_rate * duration), False)
                if inst == 'Talerz':
                    base = np.sin(2 * np.pi * 2000 * t) * np.exp(-3 * t)
                    noise = np.random.normal(0, 0.3, len(t)) * np.exp(-2 * t)
                    sound = base + noise
                elif inst == 'Stopa':
                    sound = np.sin(2 * np.pi * 60 * t) * np.exp(-10 * t)
                elif inst == 'Werbel':
                    base = np.sin(2 * np.pi * 300 * t) * np.exp(-6 * t)
                    noise = np.random.normal(0, 0.1, len(t)) * np.exp(-4 * t)
                    sound = base * 0.7 + noise * 0.3
                elif inst == 'TomTom':
                    base = np.sin(2 * np.pi * 100 * t) * np.exp(-4 * t)
                    echo = np.sin(2 * np.pi * 100 * t) * np.exp(-6 * t) * 0.4
                    sound = base + np.pad(echo, (int(sample_rate * 0.1), 0))[:len(t)]
                
                sound = (sound / np.max(np.abs(sound)) * 32767).astype(np.int16)
                self.samples[inst] = f"{inst}_default.wav"
                sf.write(self.samples[inst], sound, sample_rate)

    def export_sample_bank(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Export Sample Bank",
            action=Gtk.FileChooserAction.SAVE,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
        dialog.set_current_name("sample_bank.zip")

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            import zipfile
            filename = dialog.get_filename()
            with zipfile.ZipFile(filename, 'w') as zipf:
                for inst in self.instruments:
                    if inst in self.samples:
                        zipf.write(self.samples[inst], os.path.basename(self.samples[inst]))
                adsr_data = json.dumps(self.current_adsr)
                zipf.writestr("adsr_settings.json", adsr_data)
            self.bank_combo.append_text(os.path.basename(filename).replace(".zip", ""))
        dialog.destroy()

    def load_sample_bank(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Load Sample Bank",
            action=Gtk.FileChooserAction.OPEN,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        response = dialog.run()
    
        if response == Gtk.ResponseType.OK:
            import zipfile
            filename = dialog.get_filename()
            try:
                with zipfile.ZipFile(filename, 'r') as zipf:
                    # Extract all files to a temporary directory
                    zipf.extractall("sample_bank_temp")
                    
                    # Load samples
                    loaded_samples = False
                    for inst in self.instruments:
                        sample_path = f"sample_bank_temp/{inst}.wav"
                        if os.path.exists(sample_path):
                            self.samples[inst] = sample_path
                            loaded_samples = True
                            print(f"Loaded sample for {inst}: {sample_path}")
                    
                    # Load ADSR settings
                    adsr_file = "sample_bank_temp/adsr_settings.json"
                    if os.path.exists(adsr_file):
                        with open(adsr_file, 'r') as f:
                            self.current_adsr = json.load(f)
                        for inst in self.instruments:
                            for param, entry in self.adsr_entries[inst].items():
                                entry.set_text(str(self.current_adsr[inst][param]))
                        print("Loaded ADSR settings from bank")
    
                    # Add bank name to combo box if any samples were loaded
                    if loaded_samples:
                        bank_name = os.path.basename(filename).replace(".zip", "")
                        if bank_name not in [self.bank_combo.get_model()[i][0] for i in range(len(self.bank_combo.get_model()))]:
                            self.bank_combo.append_text(bank_name)
                            self.bank_combo.set_active(len(self.bank_combo.get_model()) - 1)  # Select the newly added bank
                        print(f"Sample bank '{bank_name}' loaded successfully")
                    else:
                        self.show_error_dialog("No valid samples found in the bank")
    
            except zipfile.BadZipFile:
                self.show_error_dialog(f"Failed to load bank: '{filename}' is not a valid ZIP file")
            except Exception as e:
                self.show_error_dialog(f"Error loading bank: {str(e)}")
        
        dialog.destroy()

# Main execution
if __name__ == "__main__":
    win = DrumSamplerApp()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
