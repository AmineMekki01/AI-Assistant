import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useWebSocket } from './useWebSocket'
import { useAudio } from './useAudio'
import type { JarvisState, JarvisActions } from '../types'

export function useJarvis(): { state: JarvisState; actions: JarvisActions } {
  const [currentTime, setCurrentTime] = useState(new Date())
  const [uiRecording, setUiRecording] = useState(false)

  const isRecordingRef = useRef(false)
  const isSpeakingRef = useRef(false)

  const {
    connectionState,
    statusMessage,
    messages,
    isRecording: wsIsRecording,
    isSpeaking,
    toggleRecording,
    sendAudioChunk
  } = useWebSocket('ws://localhost:8000/ws')

  useEffect(() => {
    isSpeakingRef.current = isSpeaking
  }, [isSpeaking])

  useEffect(() => {
    if (wsIsRecording !== isRecordingRef.current) {
      isRecordingRef.current = wsIsRecording
      setUiRecording(wsIsRecording)
    }
  }, [wsIsRecording])

  const chunkCounter = useRef(0)
  const { startRecording, stopRecording, audioLevel } = useAudio(
    useCallback((data: Float32Array) => {
      chunkCounter.current++
      if (chunkCounter.current <= 3) {
        console.log(`🎤 Audio chunk #${chunkCounter.current}:`, data.length, 'samples')
      }

      if (isRecordingRef.current && !isSpeakingRef.current) {
        sendAudioChunk(data)
      }
    }, [sendAudioChunk])
  )

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  const handleToggleRecording = useCallback(() => {
    const newState = !isRecordingRef.current
    isRecordingRef.current = newState
    setUiRecording(newState)

    if (newState) {
      chunkCounter.current = 0
      startRecording()
    } else {
      stopRecording()
    }
    toggleRecording()
  }, [startRecording, stopRecording, toggleRecording])

  const state: JarvisState = useMemo(() => ({
    connectionState,
    statusMessage,
    messages,
    isRecording: uiRecording,
    isSpeaking,
    audioLevel,
    currentTime
  }), [connectionState, statusMessage, messages, uiRecording, isSpeaking, audioLevel, currentTime])

  const actions: JarvisActions = useMemo(() => ({
    toggleRecording: handleToggleRecording
  }), [handleToggleRecording])

  return { state, actions }
}
