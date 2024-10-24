#!/usr/bin/env python3
import sys
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, GLib, Gst
import numpy as np
import librosa
import queue
import threading
from scipy.signal import find_peaks
from collections import deque
import time

class AudioAnalyzerWidget(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Audio Analyzer")
        self.set_default_size(300, 150)

        # Initialize GStreamer
        Gst.init(None)

        # Audio processing variables
        self.audio_queue = queue.Queue()
        self.sample_rate = 44100
        self.buffer_duration = 10  # Exactly 10 seconds buffer
        self.buffer = np.zeros(self.sample_rate * self.buffer_duration)
        self.buffer_filled = False
        self.last_analysis_time = time.time()

        # Create layout
        self.box = Gtk.Box()
        self.box.set_orientation(Gtk.Orientation.VERTICAL)
        self.box.set_spacing(6)
        self.box.set_margin_start(10)
        self.box.set_margin_end(10)
        self.box.set_margin_top(10)
        self.box.set_margin_bottom(10)

        # Labels for display
        self.bpm_label = Gtk.Label()
        self.bpm_label.set_text("BPM: --")
        self.time_sig_label = Gtk.Label()
        self.time_sig_label.set_text("Time Signature: --")
        self.key_label = Gtk.Label()
        self.key_label.set_text("Key: --")
        self.status_label = Gtk.Label()
        self.status_label.set_text("Status: Buffering...")

        self.box.append(self.status_label)
        self.box.append(self.bpm_label)
        self.box.append(self.time_sig_label)
        self.box.append(self.key_label)

        # Set the box as the window's child
        self.set_child(self.box)

        # Setup GStreamer pipeline
        self.setup_gst_pipeline()

        # Update timer - process queue frequently but analyze every 10s
        GLib.timeout_add(100, self.process_queue)
        GLib.timeout_add(10000, self.trigger_analysis)

    def setup_gst_pipeline(self):
        pipeline_desc = (
            "pipewiresrc ! "
            "audioconvert ! "
            "audio/x-raw,format=F32LE,channels=1,rate=44100 ! "
            "appsink name=sink emit-signals=true max-buffers=10 drop=true"
        )
        self.pipeline = Gst.parse_launch(pipeline_desc)
        self.sink = self.pipeline.get_by_name("sink")
        self.sink.connect("new-sample", self.on_new_sample)

        # Start playing
        self.pipeline.set_state(Gst.State.PLAYING)

    def on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        buffer = sample.get_buffer()

        success, map_info = buffer.map(Gst.MapFlags.READ)
        if success:
            data = np.frombuffer(map_info.data, dtype=np.float32)
            self.audio_queue.put(data)
            buffer.unmap(map_info)

        return Gst.FlowReturn.OK

    def detect_time_signature(self, onset_env):
        peaks, _ = find_peaks(onset_env, distance=20)
        if len(peaks) < 2:
            return 4

        peak_distances = np.diff(peaks)
        if len(peak_distances) == 0:
            return 4

        median_distance = np.median(peak_distances)
        beats_estimate = round(median_distance / (self.sample_rate / 120))

        if beats_estimate <= 3:
            return 3
        elif beats_estimate <= 4:
            return 4
        elif beats_estimate <= 6:
            return 6
        else:
            return 4

    def estimate_bpm(self, onset_env):
        # Find peaks in onset envelope
        peaks, _ = find_peaks(
            onset_env,
            distance=int(0.2 * self.sample_rate / 512),  # Minimum 0.2s between peaks
            prominence=0.5
        )

        if len(peaks) < 2:
            return None

        # Calculate average time between peaks
        peak_times = peaks * 512 / self.sample_rate  # Convert to seconds
        intervals = np.diff(peak_times)

        # Convert intervals to BPM
        bpms = 60.0 / intervals

        # Filter out unreasonable BPM values
        valid_bpms = bpms[(bpms >= 50) & (bpms <= 200)]

        if len(valid_bpms) == 0:
            return None

        # Use median for stability
        return float(np.median(valid_bpms))

    def analyze_audio(self):
        try:
            if not self.buffer_filled:
                if np.count_nonzero(self.buffer) < self.buffer.size * 0.8:
                    return None, 4, "Buffering..."
                self.buffer_filled = True

            audio_normalized = librosa.util.normalize(self.buffer)

            # Onset and tempo detection
            onset_env = librosa.onset.onset_strength(
                y=audio_normalized,
                sr=self.sample_rate,
                hop_length=512,
                aggregate=np.median
            )

            # BPM estimation
            bpm = self.estimate_bpm(onset_env)
            if bpm is None:
                bpm = 0.0

            # Time signature detection
            beats_in_measure = self.detect_time_signature(onset_env)

            # Key detection
            chroma = librosa.feature.chroma_cqt(
                y=audio_normalized,
                sr=self.sample_rate,
                hop_length=512
            )

            key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            chroma_mean = np.mean(chroma, axis=1)
            key_idx = int(np.argmax(chroma_mean))
            key = key_names[key_idx]

            minor_template = np.roll([1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0], key_idx)
            major_template = np.roll([1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1], key_idx)

            minor_correlation = float(np.correlate(chroma_mean, minor_template)[0])
            major_correlation = float(np.correlate(chroma_mean, major_template)[0])

            is_major = major_correlation > minor_correlation
            key = f"{key} {'major' if is_major else 'minor'}"

            return bpm, beats_in_measure, key

        except Exception as e:
            print(f"Analysis error: {e}")
            return None, 4, "Analysis error"

    def process_queue(self):
        """Process incoming audio data and update buffer"""
        while not self.audio_queue.empty():
            try:
                audio_data = self.audio_queue.get_nowait()
                data_len = len(audio_data)
                self.buffer = np.roll(self.buffer, -data_len)
                self.buffer[-data_len:] = audio_data
            except queue.Empty:
                break
            except Exception as e:
                print(f"Buffer update error: {e}")

        return True

    def trigger_analysis(self):
        """Trigger analysis every 10 seconds"""
        current_time = time.time()
        if current_time - self.last_analysis_time >= 10:
            bpm, time_sig, key = self.analyze_audio()

            def update_labels():
                if not self.buffer_filled:
                    self.status_label.set_text("Status: Buffering...")
                else:
                    self.status_label.set_text(f"Status: Analyzing {self.buffer_duration}s window")

                if bpm is not None:
                    self.bpm_label.set_text(f"BPM: {bpm:.1f}")
                    self.time_sig_label.set_text(f"Time Signature: {time_sig}/4")
                    self.key_label.set_text(f"Key: {key}")
                return False

            GLib.idle_add(update_labels)
            self.last_analysis_time = current_time

        return True

    def do_destroy(self):
        self.pipeline.set_state(Gst.State.NULL)
        Gtk.Window.do_destroy(self)

class AudioAnalyzerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.example.audioanalyzer")
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = AudioAnalyzerWidget(self)
        self.window.present()

def main():
    app = AudioAnalyzerApp()
    return app.run(sys.argv)

if __name__ == "__main__":
    main()
