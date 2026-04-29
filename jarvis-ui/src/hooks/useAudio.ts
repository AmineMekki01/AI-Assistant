import { useState, useRef, useCallback, useEffect } from 'react'

interface AudioState {
  isRecording: boolean
  audioLevel: number
  error: string | null
}

export function useAudio(onAudioData?: (data: Float32Array) => void) {
  const [state, setState] = useState<AudioState>({
    isRecording: false,
    audioLevel: 0,
    error: null
  })

  const audioContextRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const processorRef = useRef<AudioNode | null>(null)
  const workletRef = useRef<AudioWorkletNode | null>(null)
  const workletGainRef = useRef<GainNode | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const rafRef = useRef<number | null>(null)

  const forwardAudioData = useCallback((audioData: Float32Array) => {
    if (onAudioData) {
      onAudioData(new Float32Array(audioData))
    }
  }, [onAudioData])

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true
        }
      })
      streamRef.current = stream

      const audioContext = new AudioContext({ sampleRate: 16000 })
      audioContextRef.current = audioContext

      const source = audioContext.createMediaStreamSource(stream)
      sourceRef.current = source

      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 256
      analyserRef.current = analyser
      source.connect(analyser)

      const dataArray = new Uint8Array(analyser.frequencyBinCount)
      const updateLevel = () => {
        analyser.getByteFrequencyData(dataArray)
        const average = dataArray.reduce((a, b) => a + b) / dataArray.length
        const normalized = average / 255
        setState(prev => ({ ...prev, audioLevel: normalized }))
        rafRef.current = requestAnimationFrame(updateLevel)
      }
      updateLevel()

      let captureNode: AudioNode | null = null
      let silentGain: GainNode | null = null

      if (audioContext.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
        try {
          await audioContext.audioWorklet.addModule('/audio-processor.js')
          const workletNode = new AudioWorkletNode(audioContext, 'jarvis-audio-processor')
          workletNode.port.onmessage = (event) => {
            if (event.data instanceof Float32Array) {
              forwardAudioData(event.data)
            }
          }

          silentGain = audioContext.createGain()
          silentGain.gain.value = 0

          source.connect(workletNode)
          workletNode.connect(silentGain)
          silentGain.connect(audioContext.destination)

          captureNode = workletNode
          workletRef.current = workletNode
          workletGainRef.current = silentGain
        } catch (workletError) {
          console.warn('AudioWorklet unavailable, falling back to ScriptProcessorNode', workletError)
        }
      }

      if (!captureNode) {
        const processor = audioContext.createScriptProcessor(4096, 1, 1)
        processor.onaudioprocess = (e) => {
          forwardAudioData(new Float32Array(e.inputBuffer.getChannelData(0)))
        }

        source.connect(processor)
        processor.connect(audioContext.destination)
        captureNode = processor
      }

      processorRef.current = captureNode

      setState(prev => ({ ...prev, isRecording: true, error: null }))
    } catch (err) {
      setState(prev => ({
        ...prev,
        error: err instanceof Error ? err.message : 'Failed to access microphone'
      }))
    }
  }, [onAudioData])

  const stopRecording = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }

    if (processorRef.current) {
      if (workletRef.current) {
        try {
          workletRef.current.port.postMessage({ type: 'flush' })
        } catch (error) {
          console.warn('Failed to flush AudioWorklet buffer before stop', error)
        }
      }

      processorRef.current.disconnect()
      if (processorRef.current instanceof ScriptProcessorNode) {
        processorRef.current.onaudioprocess = null
      }
      processorRef.current = null
    }

    workletRef.current = null

    if (workletGainRef.current) {
      workletGainRef.current.disconnect()
      workletGainRef.current = null
    }

    if (sourceRef.current) {
      sourceRef.current.disconnect()
      sourceRef.current = null
    }

    if (analyserRef.current) {
      analyserRef.current.disconnect()
      analyserRef.current = null
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop())
      streamRef.current = null
    }

    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      void audioContextRef.current.close().catch(() => {})
      audioContextRef.current = null
    }

    setState(prev => ({ ...prev, isRecording: false, audioLevel: 0 }))
  }, [])

  useEffect(() => {
    return () => {
      stopRecording()
    }
  }, [stopRecording])

  return {
    ...state,
    startRecording,
    stopRecording
  }
}
