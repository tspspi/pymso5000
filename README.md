# Rigol MSO5xxx oscilloscope Python library (unofficial)

A simple Python library and utility to control and query data from
Rigol MSO5xxx oscilloscopes (not supporting all features of the oscilloscope,
work in progress):

## Simple example to fetch waveforms:

```
from pymso5000.mso5000 import MSO5000

with MSO5000(address = "10.0.0.123") as mso:
		print(f"Identify: {mso.identify()}")

		mso._set_channel_enable(1, True)
		mso._set_channel_enable(2, True)

		data = mso._query_waveform((1, 2))
		print(data)

		import matplotlib.pyplot as plt
		plt.plot(data['x'], data['y1'], label = "Ch1")
		plt.plot(data['x'], data['y2'], label = "Ch2")
		plt.show()
```
