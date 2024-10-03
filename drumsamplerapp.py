import gi
import random
import time
import threading
import pygame  # PyGame for playing audio

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

class DrumSamplerApp(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Drum Sampler")
        self.set_border_width(10)

        # Inicjalizacja PyGame do obsługi dźwięków
        pygame.mixer.init()

        # Layout główny
        self.grid = Gtk.Grid()
        self.add(self.grid)

        # Etykiety dla instrumentów
        self.instruments = ['Talerz', 'Stopa', 'Werbel', 'TomTom']
        self.patterns = {inst: [0] * 16 for inst in self.instruments}
        self.samples = {}  # Przechowuje ścieżki do plików audio

        # Kontenery dla instrumentów i patternów
        self.entries = {}

        for idx, instrument in enumerate(self.instruments):
            # Etykieta instrumentu
            label = Gtk.Label(label=instrument)
            self.grid.attach(label, 0, idx, 1, 1)

            # Pattern (16 kroków)
            self.entries[instrument] = []
            for step in range(16):
                entry = Gtk.Entry()
                entry.set_max_length(1)
                entry.set_text("0")
                self.grid.attach(entry, step + 1, idx, 1, 1)
                self.entries[instrument].append(entry)

        # Przycisk do losowania patternu
        self.randomize_button = Gtk.Button(label="Losuj pattern")
        self.randomize_button.connect("clicked", self.randomize_pattern)
        self.grid.attach(self.randomize_button, 0, len(self.instruments), 2, 1)

        # Przycisk do odtwarzania loopa
        self.play_button = Gtk.Button(label="Play")
        self.play_button.connect("clicked", self.play_pattern)
        self.grid.attach(self.play_button, 2, len(self.instruments), 2, 1)

        # Przycisk do zatrzymania odtwarzania
        self.stop_button = Gtk.Button(label="Stop")
        self.stop_button.connect("clicked", self.stop_pattern)
        self.grid.attach(self.stop_button, 4, len(self.instruments), 2, 1)

        # Flaga odtwarzania w pętli
        self.loop_playing = False
        self.play_thread = None

        # Przycisk do wczytania sampli
        self.load_button = Gtk.Button(label="Wczytaj Sample")
        self.load_button.connect("clicked", self.load_samples)
        self.grid.attach(self.load_button, 6, len(self.instruments), 2, 1)

    def randomize_pattern(self, widget):
        """Losuje pattern dla każdego instrumentu"""
        # Logika losowania: główne instrumenty mają powtarzające się wzory
        for inst in self.instruments:
            for i in range(16):
                if inst == 'Stopa':  # Stopa powtarza się regularnie
                    self.patterns[inst][i] = random.choice([1, 0]) if i % 4 == 0 else 0
                elif inst == 'Werbel':  # Werbel jako kontrast do stopy
                    self.patterns[inst][i] = 1 if i % 4 == 2 else 0
                elif inst == 'Talerz':  # Talerze wypełniają luki
                    self.patterns[inst][i] = random.choice([0, 1]) if self.patterns['Stopa'][i] == 0 else 0
                elif inst == 'TomTom':  # Tomtom jako akcent
                    self.patterns[inst][i] = random.choice([0, 1]) if i % 8 == 7 else 0

        # Aktualizowanie GUI z nowymi patternami
        self.update_entries()

    def update_entries(self):
        """Aktualizuje pola tekstowe zgodnie z wygenerowanym patternem"""
        for inst in self.instruments:
            for i in range(16):
                self.entries[inst][i].set_text(str(self.patterns[inst][i]))

    def load_samples(self, widget):
        """Wczytuje sample dla każdego instrumentu"""
        for inst in self.instruments:
            # Można wczytać pliki audio w MP3/WAV i przypisać do każdego instrumentu
            # Zakładając, że ścieżki do plików są zapisane w dictionary `self.samples`
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
        """Odtwarza pattern w pętli"""
        if not self.loop_playing:
            self.loop_playing = True
            self.play_thread = threading.Thread(target=self.loop_play)
            self.play_thread.start()

    def loop_play(self):
        """Loop odtwarzający dźwięki na podstawie patternu"""
        while self.loop_playing:
            for step in range(16):
                for inst in self.instruments:
                    if self.patterns[inst][step] == 1 and inst in self.samples:
                        pygame.mixer.Sound(self.samples[inst]).play()
                time.sleep(0.25)  # 250 ms przerwa między krokami

    def stop_pattern(self, widget):
        """Zatrzymuje pętlę odtwarzania"""
        self.loop_playing = False
        if self.play_thread is not None:
            self.play_thread.join()

win = DrumSamplerApp()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
