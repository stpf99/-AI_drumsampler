import gi
import random
import time
import threading
import pygame
import json
import os

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

class DrumSamplerApp(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Drum Sampler")
        self.set_border_width(10)

        pygame.mixer.init()

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(self.main_box)

        # Create toolbar
        self.create_toolbar()

        self.grid = Gtk.Grid()
        self.main_box.pack_start(self.grid, True, True, 0)

        self.instruments = ['Talerz', 'Stopa', 'Werbel', 'TomTom']
        self.patterns = {inst: [0] * 16 for inst in self.instruments}
        self.samples = {}
        self.entries = {}

        for idx, instrument in enumerate(self.instruments):
            label = Gtk.Label(label=instrument)
            self.grid.attach(label, 0, idx, 1, 1)

            self.entries[instrument] = []
            for step in range(16):
                entry = Gtk.Entry()
                entry.set_max_length(1)
                entry.set_width_chars(1)
                entry.set_text("0")
                self.grid.attach(entry, step + 1, idx, 1, 1)
                self.entries[instrument].append(entry)

        self.loop_playing = False
        self.play_thread = None
        self.bpm = 120  # Default BPM
        self.create_bpm_controls()

    def create_toolbar(self):
        toolbar = Gtk.Toolbar()
        self.main_box.pack_start(toolbar, False, False, 0)

        button_info = [
            ("media-playback-start", self.play_pattern, "Play"),
            ("media-playback-stop", self.stop_pattern, "Stop"),
            ("view-refresh", self.randomize_pattern, "Randomize"),
            ("document-open", self.load_samples, "Load Samples"),
            ("document-save", self.save_project, "Save Project"),
            ("document-open", self.load_project, "Load Project")
        ]

        for icon_name, callback, tooltip in button_info:
            button = Gtk.ToolButton()
            button.set_icon_name(icon_name)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", callback)
            toolbar.insert(button, -1)

    def create_bpm_controls(self):
        bpm_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_box.pack_start(bpm_box, False, False, 0)

        bpm_label = Gtk.Label(label="BPM:")
        bpm_box.pack_start(bpm_label, False, False, 0)

        self.bpm_entry = Gtk.Entry()
        self.bpm_entry.set_text(str(self.bpm))
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

    def bpm_step_up(self, widget):
        self.bpm = min(300, self.bpm + 5)  # Limit maximum BPM to 300
        self.bpm_entry.set_text(str(self.bpm))

    def bpm_step_down(self, widget):
        self.bpm = max(60, self.bpm - 5)  # Limit minimum BPM to 60
        self.bpm_entry.set_text(str(self.bpm))

    def randomize_pattern(self, widget):
        for inst in self.instruments:
            for i in range(16):
                if inst == 'Stopa':
                    self.patterns[inst][i] = random.choice([1, 0]) if i % 4 == 0 else 0
                elif inst == 'Werbel':
                    self.patterns[inst][i] = 1 if i % 4 == 2 else 0
                elif inst == 'Talerz':
                    self.patterns[inst][i] = random.choice([0, 1]) if self.patterns['Stopa'][i] == 0 else 0
                elif inst == 'TomTom':
                    self.patterns[inst][i] = random.choice([0, 1]) if i % 8 == 7 else 0

        self.update_entries()

    def update_entries(self):
        for inst in self.instruments:
            for i in range(16):
                self.entries[inst][i].set_text(str(self.patterns[inst][i]))

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

    def play_pattern(self, widget):
        if not self.loop_playing:
            self.loop_playing = True
            self.play_thread = threading.Thread(target=self.loop_play)
            self.play_thread.start()

    def loop_play(self):
        while self.loop_playing:
            for step in range(16):
                for inst in self.instruments:
                    if self.patterns[inst][step] == 1 and inst in self.samples:
                        pygame.mixer.Sound(self.samples[inst]).play()
                time.sleep(60 / self.bpm / 4)  # Calculate sleep time based on BPM

    def stop_pattern(self, widget):
        self.loop_playing = False
        if self.play_thread is not None:
            self.play_thread.join()

    def save_project(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Zapisz Projekt",
            action=Gtk.FileChooserAction.SAVE,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        )
        dialog.set_current_name("projekt.drsmp")
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            project_data = {
                "patterns": self.patterns,
                "samples": self.samples,
                "bpm": self.bpm
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
            self.bpm = project_data.get("bpm", 120)  # Default to 120 if not found
            self.bpm_entry.set_text(str(self.bpm))
            
            self.update_entries()
            print(f"Projekt wczytany z: {filename}")
        
        dialog.destroy()

win = DrumSamplerApp()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
