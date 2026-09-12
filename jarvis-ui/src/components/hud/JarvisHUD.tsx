import { useId } from 'react'
import { useReducedMotion } from 'framer-motion'

interface JarvisHUDProps {
  isSpeaking: boolean
  isRecording: boolean
  isListening: boolean
  audioLevel: number
}

export function JarvisHUD({ isSpeaking, isRecording, isListening, audioLevel }: JarvisHUDProps) {
  const reducedMotion = useReducedMotion()
  const id = useId().replace(/:/g, '')
  const glowId = `reactor-glow-${id}`
  const ringId = `reactor-ring-${id}`
  const active = isSpeaking || isRecording || isListening
  const inputLevel = Number.isFinite(audioLevel) ? Math.min(1, Math.max(0, audioLevel)) : 0
  // Speaking uses a visual pulse, independent of nearby microphone sounds.
  const level = isSpeaking ? 0.45 : active ? Math.sqrt(inputLevel) : 0
  const reacting = isSpeaking || isRecording || (isListening && inputLevel > 0.035)
  const expansion = 1.035 + level * 0.075

  return (
    <div className={`reactor ${isSpeaking ? 'speaking' : isRecording || isListening ? 'listening' : ''} ${reacting ? 'reacting' : ''}`} aria-hidden="true">
      <div className="reactor-aura" />
      <svg viewBox="-250 -250 500 500" className="reactor-svg">
        <defs>
          <radialGradient id={glowId}>
            <stop stopColor="var(--reactor-bright)" stopOpacity=".3" />
            <stop offset="1" stopColor="var(--reactor-color)" stopOpacity="0" />
          </radialGradient>
          <linearGradient id={ringId} x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="var(--reactor-bright)" />
            <stop offset=".5" stopColor="var(--reactor-deep)" />
            <stop offset="1" stopColor="var(--reactor-color)" />
          </linearGradient>
        </defs>

        <circle r="236" className="reactor-guide" />
        <circle r="226" className="reactor-guide" strokeDasharray="1 8" />
        <path d="M-213 -100 H-227 Q-243 -100 -243 -80 V80 Q-243 100 -227 100 H-213 M213 -100 H227 Q243 -100 243 -80 V80 Q243 100 227 100 H213" fill="none" stroke="currentColor" strokeWidth=".8" opacity=".4" />

        {/* SVG scale uses the rings' exact (0, 0) center. CSS transform origins
            on a negative viewBox can move that pivot and cause diagonal drift. */}
        <g className="reactor-pulse">
          {reacting && !reducedMotion && (
            <animateTransform attributeName="transform" type="scale"
              values={`1;${expansion};1`} keyTimes="0;0.5;1"
              calcMode="spline" keySplines=".4 0 .2 1;.4 0 .2 1"
              dur="0.95s" repeatCount="indefinite" />
          )}
          <circle r="208" fill="none" stroke={`url(#${ringId})`} strokeWidth="1.8" className="reactor-rim" />
          <g>
            {!reducedMotion && <animateTransform attributeName="transform" type="rotate" from="0 0 0" to="360 0 0" dur="80s" repeatCount="indefinite" />}
            {Array.from({ length: 48 }, (_, i) => (
              <line key={i} x1="0" y1="-181" x2="0" y2="-198"
                transform={`rotate(${i * 7.5})`} stroke="currentColor"
                strokeWidth="6" opacity={0.12 + (1 + Math.sin(i * Math.PI / 24)) * 0.27} />
            ))}
          </g>
          <circle r="172" fill="none" stroke="currentColor" strokeWidth="2.5" className="reactor-rim" opacity=".85" />
          <g>
            {!reducedMotion && <animateTransform attributeName="transform" type="rotate" from="360 0 0" to="0 0 0" dur="100s" repeatCount="indefinite" />}
            {Array.from({ length: 96 }, (_, i) => (
              <line key={i} x1="0" y1="-156" x2="0" y2={i % 8 === 0 ? -146 : -150}
                transform={`rotate(${i * 3.75})`} stroke="currentColor"
                strokeWidth="1.3" opacity={i % 8 === 0 ? .9 : .5} />
            ))}
            <circle r="138" fill="none" stroke="currentColor" strokeWidth=".8" strokeDasharray="180 65 60 65" opacity=".6" />
          </g>
          <circle r="145" fill={`url(#${glowId})`} />
          <g className="reactor-spectrum">
            {Array.from({ length: 48 }, (_, i) => (
              <line key={i} x1="0" y1="-116"
                x2="0" y2={-120 - level * (4 + (1 + Math.sin(i * 1.7)) * 4)}
                transform={`rotate(${i * 7.5})`} stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" opacity={active ? .7 : .25} />
            ))}
          </g>
          <g className="reactor-core">
            <circle r="106" fill="none" stroke="currentColor" strokeWidth=".7" opacity=".4" />
            <circle r="99" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="130 30" opacity=".8" />
            <circle r="90" fill="var(--reactor-deep)" fillOpacity=".12" stroke="currentColor" strokeOpacity=".3" />
            <circle r="67" fill="none" stroke="currentColor" strokeWidth="1" opacity=".7" />
            <circle r="62" fill="none" stroke="currentColor" strokeWidth="4" strokeDasharray="72 58" opacity=".7" />
            <circle r="49" fill="none" stroke="currentColor" strokeWidth=".7" opacity=".4" />
            {[0, 120, 240].map(angle => (
              <path key={angle} d="M-8 -75 H8 L5 -65 H-5 Z" transform={`rotate(${angle})`} fill="currentColor" opacity=".75" />
            ))}
            <circle r="29" fill={`url(#${glowId})`} stroke="currentColor" strokeWidth="1.2" />
            <circle r="9" fill="var(--reactor-bright)" className="reactor-center" />
          </g>
        </g>
        {[0, 90, 180, 270].map(angle => (
          <g key={angle} transform={`rotate(${angle})`}>
            <path d="M-5 -244 H5 M0 -249 V-239" stroke="currentColor" opacity=".6" />
          </g>
        ))}
      </svg>
      <div className="reactor-signal">
        {Array.from({ length: 25 }, (_, i) => (
          <span key={i} style={{
            height: active ? 5 + (1 + Math.sin(i * 1.9)) * (isSpeaking ? 12 : 3) + level * (15 + (1 + Math.cos(i)) * 12) : 3,
            animationDelay: `${i * .08}s`,
          }} />
        ))}
      </div>
    </div>
  )
}
