"""Reproduce the bundled original ambient loop; standard library, no external samples."""
import array
import math
import sys
import wave
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "assets/music/calm-loop.wav"
rate, seconds = 24000, 8
samples = array.array("h")
for i in range(rate * seconds):
    t = i / rate
    # Integer cycles ensure a continuous, click-free loop. Slow amplitude breathing.
    value = sum(math.sin(2 * math.pi * frequency * t) * gain for frequency, gain in ((130.75, .48), (196.125, .28), (261.625, .18)))
    value *= .78 + .12 * math.cos(2 * math.pi * t / seconds)
    samples.append(round(1800 * value))
if sys.byteorder != "little":
    samples.byteswap()
with wave.open(str(path), "wb") as output:
    output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
    output.writeframes(samples.tobytes())
