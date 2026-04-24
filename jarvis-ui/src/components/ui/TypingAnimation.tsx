import { motion } from 'framer-motion'

export function TypingAnimation() {
  return (
    <div className="typing-dots">
      {[...Array(3)].map((_, i) => (
        <motion.span
          key={i}
          className="typing-dot"
          animate={{
            opacity: [0.3, 1, 0.3],
            y: [0, -5, 0]
          }}
          transition={{
            duration: 0.6,
            repeat: Infinity,
            delay: i * 0.2
          }}
        />
      ))}
    </div>
  )
}
