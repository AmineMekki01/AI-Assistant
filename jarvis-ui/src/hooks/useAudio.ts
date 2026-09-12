import { useState, useRef, useCallback, useEffect } from 'react'

export function useAudio(onAudioData?: (data: Float32Array) => void) {
  const [state, setState] = useState({ isRecording: false, audioLevel: 0, error: null as string | null })
  const callback = useRef(onAudioData)
  callback.current = onAudioData
  const generation = useRef(0)
  const starting = useRef(false)
  const context = useRef<AudioContext | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const processor = useRef<AudioWorkletNode | ScriptProcessorNode | null>(null)
  const raf = useRef<number | null>(null)
  const flushed = useRef<(() => void) | null>(null)

  const cleanup = useCallback(() => {
    if (raf.current !== null) cancelAnimationFrame(raf.current)
    raf.current = null
    if (typeof AudioWorkletNode !== 'undefined' && processor.current instanceof AudioWorkletNode) {
      processor.current.port.onmessage = null
      processor.current.port.close()
    } else if (processor.current) {
      (processor.current as ScriptProcessorNode).onaudioprocess = null
    }
    processor.current?.disconnect()
    processor.current = null
    stream.current?.getTracks().forEach(track => { track.onended = null; track.stop() })
    stream.current = null
    const ctx = context.current
    context.current = null
    if (ctx && ctx.state !== 'closed') void ctx.close().catch(() => {})
  }, [])

  const stopRecording = useCallback(async () => {
    ++generation.current
    starting.current = false
    // Deliver the final partial frame before sending recording=false.
    if (typeof AudioWorkletNode !== 'undefined' && processor.current instanceof AudioWorkletNode) {
      const node = processor.current
      await new Promise<void>(resolve => {
        const timer = setTimeout(resolve, 150)
        flushed.current = () => { clearTimeout(timer); resolve() }
        node.port.postMessage({ type: 'flush' })
      })
      flushed.current = null
    }
    cleanup()
    setState(prev => ({ ...prev, isRecording: false, audioLevel: 0 }))
  }, [cleanup])

  const startRecording = useCallback(async (): Promise<boolean> => {
    if (starting.current || context.current) return false
    starting.current = true
    const attempt = ++generation.current
    let acquired: MediaStream | null = null
    try {
      acquired = await navigator.mediaDevices.getUserMedia({ audio: {
        sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true
      } })
      if (attempt !== generation.current) {
        acquired.getTracks().forEach(track => track.stop())
        return false
      }
      stream.current = acquired
      const ctx = new AudioContext({ sampleRate: 16000 })
      context.current = ctx
      await ctx.resume()
      if (attempt !== generation.current) return false
      const source = ctx.createMediaStreamSource(acquired)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 256
      source.connect(analyser)
      const silent = ctx.createGain()
      silent.gain.value = 0
      silent.connect(ctx.destination)
      if (ctx.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
        try {
          await ctx.audioWorklet.addModule('/audio-processor.js')
          if (attempt !== generation.current) return false
          const node = new AudioWorkletNode(ctx, 'jarvis-audio-processor')
          node.port.onmessage = event => {
            if (event.data instanceof Float32Array) callback.current?.(event.data)
            else if (event.data?.type === 'flushed') flushed.current?.()
          }
          processor.current = node
        } catch (error) {
          if (attempt !== generation.current) return false
          console.warn('Using fallback microphone capture', error)
        }
      }
      if (!processor.current) {
        const node = ctx.createScriptProcessor(1024, 1, 1)
        node.onaudioprocess = event => callback.current?.(new Float32Array(event.inputBuffer.getChannelData(0)))
        processor.current = node
      }
      source.connect(processor.current)
      processor.current.connect(silent)
      acquired.getTracks().forEach(track => {
        track.onended = () => {
          void stopRecording()
          setState(prev => ({ ...prev, error: 'Microphone disconnected. Reconnect it and click the microphone.' }))
        }
      })
      const levels = new Uint8Array(analyser.frequencyBinCount)
      const update = () => {
        analyser.getByteFrequencyData(levels)
        setState(prev => ({ ...prev, audioLevel: levels.reduce((a, b) => a + b, 0) / levels.length / 255 }))
        raf.current = requestAnimationFrame(update)
      }
      update()
      setState(prev => ({ ...prev, isRecording: true, error: null }))
      return true
    } catch (error) {
      if (attempt === generation.current) {
        cleanup()
        setState({ isRecording: false, audioLevel: 0, error: error instanceof Error ? error.message : 'Microphone unavailable' })
      }
      return false
    } finally {
      if (attempt === generation.current) starting.current = false
    }
  }, [cleanup, stopRecording])

  useEffect(() => {
    const resume = () => {
      if (document.visibilityState === 'visible' && context.current?.state === 'suspended') {
        void context.current.resume().catch(() => {
          setState(prev => ({ ...prev, error: 'Click the microphone to resume audio.' }))
        })
      }
    }
    document.addEventListener('visibilitychange', resume)
    return () => {
      ++generation.current
      cleanup()
      document.removeEventListener('visibilitychange', resume)
    }
  }, [cleanup])

  return { ...state, startRecording, stopRecording }
}
