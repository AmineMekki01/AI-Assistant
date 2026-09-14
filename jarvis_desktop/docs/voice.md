# Voice and turn handling

The voice system is designed for hands-free use: say the wake word for the
first request, then continue speaking naturally while the follow-up window is
open. The default window is five minutes after JARVIS finishes speaking.

## Listening states

| State | What happens |
| --- | --- |
| Waiting | The microphone watches for the configured wake word. Clap may also activate JARVIS when enabled. |
| Recording | Speech is streamed to the Realtime input buffer. |
| JARVIS speaking | Microphone capture ignores speech so speaker output is not treated as a command. |
| Follow-up window | Normal speech starts a new recording without saying “Hey JARVIS” again. |
| Resume delay | A short delay after assistant speech prevents playback tail audio from being captured. |

The UI receives native microphone levels from the backend, so it does not open
a second browser microphone stream.

## When a request ends

The listener uses voice activity detection when available and an energy
fallback when it is not. It requires a short run of speech frames before
arming a recording. Silence ends a request after a duration that grows with
the amount already spoken:

| Recorded speech | Silence before commit |
| --- | --- |
| Under 1.5 seconds | 1.2 seconds |
| 1.5–4 seconds | 1.8 seconds |
| Over 4 seconds | 2.1 seconds |

The maximum recording length is controlled by
`JARVIS_VOICE_MAX_RECORDING_SECONDS` and defaults to 24 seconds. The adaptive
silence rule is there to avoid cutting off people who pause in the middle of a
longer sentence.

## Follow-up listening and interruptions

When assistant playback ends, JARVIS waits
`JARVIS_VOICE_MIC_RESUME_SECONDS` before listening again. It then opens the
follow-up window for `JARVIS_VOICE_FOLLOWUP_SECONDS`. Defaults are 0.2 seconds
and 300 seconds.

Starting a new recording interrupts a current assistant response, clears queued
assistant audio, and starts a new input turn. This is how a user can speak over
JARVIS without pressing a control in the UI.

## Speaker verification

When `JARVIS_SPEAKER_VERIFICATION_ENABLED=true`, every accepted recording is
checked against the enrolled profile before any audio is committed to the model.
If verification fails, JARVIS does not send the audio and reports a rejection
to the UI. A missing or unavailable profile also blocks native voice commands
while verification is enabled.

Install the packages in `requirements-speaker.txt` into the same Python
environment as the backend, then enroll a profile in the settings UI. The
profile defaults to `~/.jarvis/voice/speaker_profile.json`. JARVIS warms the
model and profile in a background thread at startup so the first check does not
pay the full loading cost.

Clap activation is disabled when speaker verification is enabled because a clap
cannot prove who made it.

## Common symptoms

| Symptom | Check |
| --- | --- |
| No transcript after speaking | Confirm Microphone permission, native listener startup logs, and that the wake word is armed. |
| First request works, next one does not | Check the UI/status for `speaking` or `resume delay`; the follow-up window begins only after playback is released. |
| A sentence is cut off | Increase `JARVIS_VOICE_MAX_RECORDING_SECONDS`; inspect voice activity logs and microphone input level. |
| JARVIS answers to another person | Enable speaker verification and enroll a new profile. |
| Native listener unavailable | Install `openwakeword` and `pyaudio`, plus the PortAudio system package. |
