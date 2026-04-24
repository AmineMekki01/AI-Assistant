import { useEffect, useRef } from 'react'

interface JarvisHUDProps {
  isSpeaking: boolean
  isRecording: boolean
  audioLevel: number
}

function FlowingWave({
  color,
  baseRadius,
  speed,
  amplitude,
  frequency,
  phase,
  isActive,
  audioLevel,
  glow,
}: {
  color: string
  baseRadius: number
  speed: number
  amplitude: number
  frequency: number
  phase: number
  isActive: boolean
  audioLevel: number
  glow: number
}) {
  const pathRef = useRef<SVGPathElement>(null)
  const animRef = useRef<number>()

  useEffect(() => {
    const animate = () => {
      if (pathRef.current) {
        const numPoints = 160
        const pts: string[] = []
        const t = performance.now() * 0.001

        const speakBoost = isActive ? 2.2 + audioLevel * 3.5 : 0.5
        const chaosBoost = isActive ? audioLevel * 25 : 0

        for (let i = 0; i <= numPoints; i++) {
          const angle = (i / numPoints) * Math.PI * 2
          const wave1 = Math.sin(angle * frequency + t * speed + phase) * amplitude
          const wave2 = Math.sin(angle * frequency * 2.3 - t * speed * 0.7) * (amplitude * 0.6)
          const wave3 = Math.cos(angle * frequency * 0.5 + t * speed * 1.3) * (amplitude * 0.4)
          const jitter = isActive
            ? Math.sin(angle * 17 + t * 8) * chaosBoost * 0.4 +
              Math.cos(angle * 23 - t * 11) * chaosBoost * 0.3
            : 0
          const noise = (wave1 + wave2 + wave3) * speakBoost + jitter

          const r = baseRadius + noise
          const x = Math.cos(angle) * r
          const y = Math.sin(angle) * r
          pts.push(`${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`)
        }

        pathRef.current.setAttribute('d', pts.join(' ') + ' Z')
      }
      animRef.current = requestAnimationFrame(animate)
    }
    animRef.current = requestAnimationFrame(animate)
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current)
    }
  }, [baseRadius, speed, amplitude, frequency, phase, isActive, audioLevel])

  return (
    <path
      ref={pathRef}
      fill={color}
      fillOpacity={isActive ? 0.25 : 0.1}
      stroke={color}
      strokeWidth="1.2"
      strokeOpacity={isActive ? 0.9 : 0.4}
      style={{ filter: `drop-shadow(0 0 ${glow}px ${color})` }}
    />
  )
}

function RadialSpectrum({
  isActive,
  audioLevel,
  color,
}: {
  isActive: boolean
  audioLevel: number
  color: string
}) {
  const groupRef = useRef<SVGGElement>(null)
  const animRef = useRef<number>()

  useEffect(() => {
    const animate = () => {
      if (groupRef.current) {
        const lines = groupRef.current.children
        const t = performance.now() * 0.003
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i] as SVGLineElement
          const base = 6
          const variance = isActive
            ? Math.abs(Math.sin(t * 2 + i * 0.3)) * 32 +
              Math.abs(Math.sin(t * 5 + i * 0.7)) * 18 +
              audioLevel * 55
            : Math.abs(Math.sin(t * 0.3 + i * 0.1)) * 3
          const h = base + variance
          const angle = (i / lines.length) * Math.PI * 2
          const x1 = Math.cos(angle) * 78
          const y1 = Math.sin(angle) * 78
          const x2 = Math.cos(angle) * (78 + h)
          const y2 = Math.sin(angle) * (78 + h)
          line.setAttribute('x1', x1.toFixed(2))
          line.setAttribute('y1', y1.toFixed(2))
          line.setAttribute('x2', x2.toFixed(2))
          line.setAttribute('y2', y2.toFixed(2))
        }
      }
      animRef.current = requestAnimationFrame(animate)
    }
    animRef.current = requestAnimationFrame(animate)
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current)
    }
  }, [isActive, audioLevel])

  return (
    <g ref={groupRef}>
      {[...Array(96)].map((_, i) => (
        <line
          key={i}
          stroke={color}
          strokeWidth="1.2"
          strokeOpacity={isActive ? 0.9 : 0.3}
          strokeLinecap="round"
        />
      ))}
    </g>
  )
}

function PulseRings({ isActive, color }: { isActive: boolean; color: string }) {
  if (!isActive) return null
  return (
    <g>
      {[0, 1, 2].map((i) => (
        <circle
          key={i}
          cx="0"
          cy="0"
          r="30"
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          style={{
            animation: `pulse-ring 2s ease-out infinite`,
            animationDelay: `${i * 0.66}s`,
            transformOrigin: 'center',
          }}
        />
      ))}
    </g>
  )
}

function ScanBeam({ isActive, color }: { isActive: boolean; color: string }) {
  if (!isActive) return null
  return (
    <g style={{ animation: 'scan-sweep 3s linear infinite', transformOrigin: 'center' }}>
      <defs>
        <linearGradient id="scanGradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor={color} stopOpacity="0" />
          <stop offset="50%" stopColor={color} stopOpacity="0.15" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M 0 0 L -220 -40 A 220 220 0 0 1 -220 40 Z" fill="url(#scanGradient)" />
    </g>
  )
}

function EnergyBursts({ isActive, audioLevel, color }: { isActive: boolean; audioLevel: number; color: string }) {
  const groupRef = useRef<SVGGElement>(null)
  const animRef = useRef<number>()

  useEffect(() => {
    if (!isActive) return
    const animate = () => {
      if (groupRef.current) {
        const lines = groupRef.current.children
        const t = performance.now() * 0.001
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i] as SVGLineElement
          const angle = (i / lines.length) * Math.PI * 2 + t * 0.3
          const burst = Math.max(0, Math.sin(t * 3 + i * 1.3)) * (25 + audioLevel * 40)
          const innerR = 195
          const outerR = innerR + burst
          line.setAttribute('x1', (Math.cos(angle) * innerR).toFixed(2))
          line.setAttribute('y1', (Math.sin(angle) * innerR).toFixed(2))
          line.setAttribute('x2', (Math.cos(angle) * outerR).toFixed(2))
          line.setAttribute('y2', (Math.sin(angle) * outerR).toFixed(2))
          line.setAttribute('opacity', String(Math.max(0.2, burst / 50)))
        }
      }
      animRef.current = requestAnimationFrame(animate)
    }
    animRef.current = requestAnimationFrame(animate)
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current)
    }
  }, [isActive, audioLevel])

  if (!isActive) return null
  return (
    <g ref={groupRef}>
      {[...Array(24)].map((_, i) => (
        <line key={i} stroke={color} strokeWidth="2" strokeLinecap="round" />
      ))}
    </g>
  )
}

export function JarvisHUD({ isSpeaking, isRecording, audioLevel }: JarvisHUDProps) {
  const primary = isRecording ? '#ef4444' : '#00f0ff'
  const secondary = '#ff2d92'
  const isActive = isSpeaking || isRecording

  return (
    <div className="jarvis-hud-wrapper">
      <div className="hud-bracket tl" />
      <div className="hud-bracket tr" />
      <div className="hud-bracket bl" />
      <div className="hud-bracket br" />

      <div className="hud-side-marker left">
        <div className="marker-line" />
        <div className="marker-square" />
        <div className="marker-line short" />
      </div>
      <div className="hud-side-marker right">
        <div className="marker-line short" />
        <div className="marker-square" />
        <div className="marker-line" />
      </div>

      <div className={`hud-main ${isSpeaking ? 'speaking' : ''} ${isRecording ? 'recording' : ''}`}>
        <svg viewBox="-250 -250 500 500" className="hud-svg">
          <defs>
            <radialGradient id="coreGlow">
              <stop offset="0%" stopColor={primary} stopOpacity="0.8" />
              <stop offset="60%" stopColor={primary} stopOpacity="0.2" />
              <stop offset="100%" stopColor={primary} stopOpacity="0" />
            </radialGradient>
            <radialGradient id="centerDotGlow">
              <stop offset="0%" stopColor="#ffffff" stopOpacity="1" />
              <stop offset="50%" stopColor={primary} stopOpacity="0.8" />
              <stop offset="100%" stopColor={primary} stopOpacity="0" />
            </radialGradient>
          </defs>

          <circle
            cx="0"
            cy="0"
            r="240"
            fill="none"
            stroke={primary}
            strokeWidth="0.5"
            strokeDasharray="1 3"
            opacity="0.3"
          />

          <g className="hud-rotate-slow">
            <circle
              cx="0"
              cy="0"
              r="222"
              fill="none"
              stroke={primary}
              strokeWidth="1"
              strokeDasharray="180 40 120 40 80 40"
              opacity="0.7"
            />
          </g>

          <g className="hud-rotate-reverse-slow">
            {[...Array(72)].map((_, i) => {
              const angle = (i / 72) * 360
              const isMajor = i % 6 === 0
              const isMid = i % 3 === 0
              return (
                <line
                  key={i}
                  x1="0"
                  y1={-210}
                  x2="0"
                  y2={isMajor ? -195 : isMid ? -202 : -206}
                  stroke={primary}
                  strokeWidth={isMajor ? 1.5 : 1}
                  opacity={isMajor ? 0.9 : isMid ? 0.6 : 0.3}
                  transform={`rotate(${angle})`}
                />
              )
            })}
          </g>

          <g className="hud-rotate-medium">
            <circle
              cx="0"
              cy="0"
              r="170"
              fill="none"
              stroke={primary}
              strokeWidth="0.8"
              strokeDasharray="2 6"
              opacity="0.5"
            />
          </g>

          <circle
            cx="0"
            cy="0"
            r="155"
            fill="none"
            stroke={primary}
            strokeWidth="1"
            strokeDasharray="100 30 60 30 80 40"
            opacity="0.8"
          />

          <RadialSpectrum isActive={isActive} audioLevel={audioLevel} color={primary} />

          <EnergyBursts isActive={isSpeaking} audioLevel={audioLevel} color={primary} />

          <ScanBeam isActive={isSpeaking} color={primary} />

          <PulseRings isActive={isSpeaking} color={primary} />

          <FlowingWave
            color={primary}
            baseRadius={100}
            speed={1.2}
            amplitude={15}
            frequency={5}
            phase={0}
            isActive={isActive}
            audioLevel={audioLevel}
            glow={isActive ? 12 : 4}
          />

          <FlowingWave
            color={secondary}
            baseRadius={95}
            speed={-1.5}
            amplitude={18}
            frequency={4}
            phase={Math.PI / 2}
            isActive={isActive}
            audioLevel={audioLevel}
            glow={isActive ? 14 : 5}
          />

          <g className="hud-rotate-fast">
            <circle
              cx="0"
              cy="0"
              r="72"
              fill="none"
              stroke={primary}
              strokeWidth="0.8"
              strokeDasharray="3 2"
              opacity="0.7"
            />
          </g>

          <g className="hud-rotate-reverse-fast">
            {[...Array(56)].map((_, i) => {
              const angle = (i / 56) * Math.PI * 2
              return (
                <circle
                  key={i}
                  cx={Math.cos(angle) * 60}
                  cy={Math.sin(angle) * 60}
                  r="1.2"
                  fill={primary}
                  opacity={i % 4 === 0 ? 1 : 0.5}
                />
              )
            })}
          </g>

          <circle cx="0" cy="0" r="40" fill="url(#coreGlow)" />

          <circle
            cx="0"
            cy="0"
            r="22"
            fill="none"
            stroke={primary}
            strokeWidth="2"
            opacity="0.9"
          />

          {[...Array(8)].map((_, i) => {
            const angle = (i / 8) * 360
            return (
              <line
                key={i}
                x1="0"
                y1={-12}
                x2="0"
                y2={-20}
                stroke={primary}
                strokeWidth="1.5"
                opacity="0.9"
                transform={`rotate(${angle})`}
              />
            )
          })}

          <circle cx="0" cy="0" r="10" fill="url(#centerDotGlow)" />
          <circle cx="0" cy="0" r="4" fill="#ffffff" />

          {[0, 90, 180, 270].map((angle) => (
            <g key={angle} transform={`rotate(${angle})`}>
              <rect
                x="-3"
                y="-230"
                width="6"
                height="6"
                fill="none"
                stroke={primary}
                strokeWidth="1"
                opacity="0.8"
              />
            </g>
          ))}
        </svg>

        <div className="orbit-container">
          {[...Array(4)].map((_, i) => (
            <div
              key={i}
              className="orbit"
              style={{
                animationDuration: `${12 + i * 4}s`,
                animationDirection: i % 2 === 0 ? 'normal' : 'reverse',
              }}
            >
              <div className="orbit-particle" style={{ background: i % 2 === 0 ? primary : secondary }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
