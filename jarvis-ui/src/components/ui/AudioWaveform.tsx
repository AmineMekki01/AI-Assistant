import { motion } from 'framer-motion'

interface AudioWaveformProps {
  isActive: boolean
  audioLevel: number
}

export function AudioWaveform({ isActive, audioLevel }: AudioWaveformProps) {
  return (
    <div className="waveform-container">
      {[...Array(20)].map((_, i) => (
        <motion.div
          key={i}
          className="waveform-bar"
          animate={{
            height: isActive ? [4, 4 + audioLevel * 40 + Math.random() * 20, 4] : 4,
            opacity: isActive ? [0.5, 1, 0.5] : 0.3
          }}
          transition={{
            duration: 0.2,
            repeat: Infinity,
            delay: i * 0.02
          }}
        />
      ))}
    </div>
  )
}
