import { useCallback, useEffect, useRef, useState } from 'react'
import { useSettings } from '../../../hooks/useSettings'
import type { SpeakerProfileStatus } from '../../../types'

function mergeAudioBuffers(buffers: Float32Array[]) {
  const totalLength = buffers.reduce((sum, buffer) => sum + buffer.length, 0)
  const merged = new Float32Array(totalLength)
  let offset = 0

  buffers.forEach(buffer => {
    merged.set(buffer, offset)
    offset += buffer.length
  })

  return merged
}

function encodeWav(samples: Float32Array, sampleRate: number) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)

  const writeString = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i += 1) {
      view.setUint8(offset + i, value.charCodeAt(i))
    }
  }

  writeString(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(8, 'WAVE')
  writeString(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  let offset = 44
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
    offset += 2
  }

  return new Blob([view], { type: 'audio/wav' })
}

export function VoiceTab() {
  const settings = useSettings()
  const [speakerProfile, setSpeakerProfile] = useState<SpeakerProfileStatus | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [recordedAudio, setRecordedAudio] = useState<Blob | null>(null)
  const [recordedAudioUrl, setRecordedAudioUrl] = useState<string | null>(null)
  const [isRecordingSample, setIsRecordingSample] = useState(false)
  const [recordingSeconds, setRecordingSeconds] = useState(0)
  const [localMessage, setLocalMessage] = useState<string | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)

  const audioContextRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const sampleBuffersRef = useRef<Float32Array[]>([])
  const timerRef = useRef<number | null>(null)

  const refreshSpeakerProfile = useCallback(async () => {
    const status = await settings.getSpeakerProfileStatus()
    setSpeakerProfile(status)
  }, [settings])

  useEffect(() => {
    refreshSpeakerProfile()
  }, [refreshSpeakerProfile])

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current)
      }
      processorRef.current?.disconnect()
      sourceRef.current?.disconnect()
      streamRef.current?.getTracks().forEach(track => track.stop())
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        void audioContextRef.current.close()
      }
      if (recordedAudioUrl) {
        URL.revokeObjectURL(recordedAudioUrl)
      }
    }
  }, [recordedAudioUrl])

  const stopRecording = useCallback(async () => {
    if (!isRecordingSample) {
      return
    }

    setIsRecordingSample(false)
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }

    processorRef.current?.disconnect()
    sourceRef.current?.disconnect()
    streamRef.current?.getTracks().forEach(track => track.stop())

    const sampleRate = audioContextRef.current?.sampleRate ?? 44100
    const bufferedSamples = mergeAudioBuffers(sampleBuffersRef.current)
    sampleBuffersRef.current = []

    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      await audioContextRef.current.close().catch(() => {})
    }
    audioContextRef.current = null
    streamRef.current = null
    sourceRef.current = null
    processorRef.current = null

    if (!bufferedSamples.length) {
      setLocalError('No microphone audio was captured. Please try again.')
      return
    }

    const wavBlob = encodeWav(bufferedSamples, sampleRate)
    if (recordedAudioUrl) {
      URL.revokeObjectURL(recordedAudioUrl)
    }
    const url = URL.createObjectURL(wavBlob)
    setRecordedAudio(wavBlob)
    setRecordedAudioUrl(url)
    setLocalMessage('Recording ready. You can enroll it now.')
    setLocalError(null)
  }, [isRecordingSample, recordedAudioUrl])

  const startRecording = useCallback(async () => {
    if (isRecordingSample) {
      return
    }

    setLocalError(null)
    setLocalMessage(null)
    setRecordedAudio(null)
    if (recordedAudioUrl) {
      URL.revokeObjectURL(recordedAudioUrl)
      setRecordedAudioUrl(null)
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setLocalError('Microphone recording is not supported in this browser.')
      return
    }

    const AudioContextCtor = window.AudioContext || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AudioContextCtor) {
      setLocalError('AudioContext is not available in this browser.')
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const audioContext = new AudioContextCtor()
      await audioContext.resume().catch(() => {})
      const source = audioContext.createMediaStreamSource(stream)
      const processor = audioContext.createScriptProcessor(4096, 1, 1)
      const silentGain = audioContext.createGain()
      silentGain.gain.value = 0

      sampleBuffersRef.current = []
      processor.onaudioprocess = event => {
        const input = event.inputBuffer.getChannelData(0)
        sampleBuffersRef.current.push(new Float32Array(input))
      }

      source.connect(processor)
      processor.connect(silentGain)
      silentGain.connect(audioContext.destination)

      audioContextRef.current = audioContext
      streamRef.current = stream
      sourceRef.current = source
      processorRef.current = processor
      setIsRecordingSample(true)
      setRecordingSeconds(0)
      timerRef.current = window.setInterval(() => {
        setRecordingSeconds(previous => previous + 1)
      }, 1000)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to access the microphone.'
      setLocalError(message)
    }
  }, [isRecordingSample, recordedAudioUrl])

  const handleEnrollFiles = useCallback(async () => {
    if (!selectedFiles.length) {
      setLocalError('Choose one or more audio files first.')
      return
    }

    setLocalError(null)
    setLocalMessage(null)
    const result = await settings.enrollSpeakerProfile(selectedFiles)
    if (result?.success) {
      setSelectedFiles([])
      setRecordedAudio(null)
      if (recordedAudioUrl) {
        URL.revokeObjectURL(recordedAudioUrl)
        setRecordedAudioUrl(null)
      }
      setLocalMessage('Speaker profile enrolled from uploaded audio.')
      await refreshSpeakerProfile()
      return
    }

    setLocalError(result?.error || settings.error || 'Failed to enroll speaker profile.')
  }, [recordedAudioUrl, refreshSpeakerProfile, selectedFiles, settings])

  const handleEnrollRecording = useCallback(async () => {
    if (!recordedAudio) {
      setLocalError('Record a microphone sample first.')
      return
    }

    setLocalError(null)
    setLocalMessage(null)
    const result = await settings.enrollSpeakerProfile([recordedAudio])
    if (result?.success) {
      setLocalMessage('Speaker profile enrolled from the recorded sample.')
      setRecordedAudio(null)
      if (recordedAudioUrl) {
        URL.revokeObjectURL(recordedAudioUrl)
        setRecordedAudioUrl(null)
      }
      await refreshSpeakerProfile()
      return
    }

    setLocalError(result?.error || settings.error || 'Failed to enroll speaker profile.')
  }, [recordedAudio, recordedAudioUrl, refreshSpeakerProfile, settings])

  const handleClearProfile = useCallback(async () => {
    const ok = await settings.clearSpeakerProfile()
    if (!ok) {
      setLocalError(settings.error || 'Failed to clear the speaker profile.')
      return
    }

    setSelectedFiles([])
    setRecordedAudio(null)
    if (recordedAudioUrl) {
      URL.revokeObjectURL(recordedAudioUrl)
      setRecordedAudioUrl(null)
    }
    setLocalMessage('Speaker profile cleared.')
    await refreshSpeakerProfile()
  }, [recordedAudioUrl, refreshSpeakerProfile, settings])

  const sampleLabel = selectedFiles.length > 0
    ? `${selectedFiles.length} file${selectedFiles.length > 1 ? 's' : ''} selected`
    : 'No audio file selected'

  return (
    <div className="tab-content">
      <section className="settings-section">
        <h3>🎙️ Voice Settings</h3>

        <label className="checkbox toggle">
          <input
            type="checkbox"
            checked={settings.settings.voice.enabled}
            onChange={e => settings.updateVoice({ enabled: e.target.checked })}
          />
          <span className="toggle-slider"></span>
          Enable voice wake word
        </label>

        <div className="form-group">
          <label>Wake Word</label>
          <input
            type="text"
            value={settings.settings.voice.wakeWord}
            onChange={e => settings.updateVoice({ wakeWord: e.target.value })}
            placeholder="Hey JARVIS"
          />
        </div>

        <div className="form-group">
          <label>Wake Word Sensitivity</label>
          <input
            type="range"
            min="0.1"
            max="1"
            step="0.1"
            value={settings.settings.voice.sensitivity}
            onChange={e => settings.updateVoice({ sensitivity: parseFloat(e.target.value) })}
          />
          <span className="range-value">{settings.settings.voice.sensitivity}</span>
        </div>
      </section>

      <section className="settings-section">
        <div className="section-header">
          <h3>🧬 Speaker Verification</h3>
          <span className={`status-badge ${speakerProfile?.profileExists ? 'success' : 'idle'}`}>
            {speakerProfile?.profileExists ? 'Profile enrolled' : 'No profile yet'}
          </span>
        </div>

        <p className="section-desc">
          Enroll your voice so JARVIS can recognize you and avoid responding to every nearby voice.
          If no profile is enrolled, speaker verification cannot tell your voice apart from others.
        </p>

        <div className="status-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
          <div className="status-item"><span className="status-label">Verification</span><span className={`status-value ${speakerProfile?.verificationEnabled ? 'active' : ''}`}>{speakerProfile?.verificationEnabled ? 'AVAILABLE' : 'NOT ENABLED'}</span></div>
          <div className="status-item"><span className="status-label">Profile</span><span className={`status-value ${speakerProfile?.profileExists ? 'active' : ''}`}>{speakerProfile?.profileExists ? 'ENROLLED' : 'EMPTY'}</span></div>
          <div className="status-item"><span className="status-label">Embeddings</span><span className="status-value active">{speakerProfile?.embeddingCount ?? 0}</span></div>
          <div className="status-item"><span className="status-label">Threshold</span><span className="status-value active">{speakerProfile ? speakerProfile.threshold.toFixed(2) : '--'}</span></div>
        </div>

        <div className="form-group">
          <label>Voice profile file upload</label>
          <input
            type="file"
            accept="audio/*"
            multiple
            onChange={e => setSelectedFiles(Array.from(e.target.files ?? []))}
          />
          <div className="range-value" style={{ marginTop: '0.5rem' }}>{sampleLabel}</div>
        </div>

        <div className="button-group">
          <button className="btn-primary" onClick={handleEnrollFiles} disabled={settings.isLoading || selectedFiles.length === 0}>
            Enroll uploaded audio
          </button>
          <button className="btn-secondary" onClick={refreshSpeakerProfile} disabled={settings.isLoading}>
            Refresh status
          </button>
          <button className="btn-secondary" onClick={handleClearProfile} disabled={settings.isLoading || !speakerProfile?.profileExists}>
            Clear profile
          </button>
        </div>

        <div className="form-group">
          <label>Record directly in the app</label>
          <div className="button-group">
            {!isRecordingSample ? (
              <button className="btn-primary" onClick={startRecording} disabled={settings.isLoading}>
                Start microphone recording
              </button>
            ) : (
              <button className="btn-primary" onClick={stopRecording}>
                Stop recording ({recordingSeconds}s)
              </button>
            )}
            <button className="btn-secondary" onClick={handleEnrollRecording} disabled={settings.isLoading || !recordedAudio}>
              Enroll recorded sample
            </button>
          </div>
          <p className="section-desc" style={{ marginTop: '0.5rem' }}>
            Record in a quiet room and speak naturally for 10–30 seconds. The app saves the recording as a WAV sample before enrollment.
          </p>
          {recordedAudioUrl && (
            <audio controls src={recordedAudioUrl} style={{ width: '100%', marginTop: '0.75rem' }} />
          )}
        </div>

        {speakerProfile?.loadError && (
          <div className="error-message">Speaker profile warning: {speakerProfile.loadError}</div>
        )}

        {localMessage && <div className="status-message">{localMessage}</div>}
        {localError && <div className="error-message">{localError}</div>}
      </section>
    </div>
  )
}
