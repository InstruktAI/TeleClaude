# Input: chiptunes-audio

<!-- Brain dump — raw thoughts, ideas, context. Prepare when ready. -->

I want a new option to play ChipTunes audio. I will dump a lot of `.sid` tracks in the audio folder in the assets slash audio folder. And you can use this example as inspiration, in the hope that yuo know how to handle it:

```py
# Taken from https://libsidplayfp-python.readthedocs.io/en/latest/example.html:
player = libsidplayfp.SidPlayfp()

config = player.config  # get the currently loaded SidConfig instance
config.sid_emulation = emulation
config.playback = libsidplayfp.Playback.STEREO
config.frequency = 44100
player.configure()  # configure the player/emulation

tune = libsidplayfp.SidTune(b'Phat_Frog_2SID.sid')
player.load(tune)


```

I dont know how to play it, but I hope you do ;)

It should of course become part of the runtime settings, just like the TTS option, which is now toggleable via the letter V for voice, and it has a speaker icon in the bottom, which I would like to go to this new feature, and the text to speech should get another icon. Probably something like a talking mouth. Yes, that is probably or some face that is speaking, you know those icons.
