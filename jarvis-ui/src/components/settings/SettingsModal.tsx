import { useState } from 'react'
import { motion } from 'framer-motion'
import { IntegrationsTab, PersonalTab, VoiceTab, AboutTab } from './tabs'
import './SettingsModal.css'

type Tab = 'integrations' | 'personal' | 'voice' | 'about'

interface SettingsModalProps {
  onClose: () => void
}

export function SettingsModal({ onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<Tab>('integrations')

  return (
    <div className="settings-modal-overlay" onClick={onClose}>
      <motion.div
        className="settings-modal"
        onClick={e => e.stopPropagation()}
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        transition={{ duration: 0.2 }}
      >
        <div className="settings-header">
          <h2>⚙️ Settings</h2>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        <div className="settings-tabs">
          <button
            className={activeTab === 'integrations' ? 'active' : ''}
            onClick={() => setActiveTab('integrations')}
          >
            🔌 Integrations
          </button>
          <button
            className={activeTab === 'personal' ? 'active' : ''}
            onClick={() => setActiveTab('personal')}
          >
            👤 Personal
          </button>
          <button
            className={activeTab === 'voice' ? 'active' : ''}
            onClick={() => setActiveTab('voice')}
          >
            🎙️ Voice
          </button>
          <button
            className={activeTab === 'about' ? 'active' : ''}
            onClick={() => setActiveTab('about')}
          >
            ℹ️ About
          </button>
        </div>

        <div className="settings-content">
          {activeTab === 'integrations' && <IntegrationsTab />}
          {activeTab === 'personal' && <PersonalTab />}
          {activeTab === 'voice' && <VoiceTab />}
          {activeTab === 'about' && <AboutTab />}
        </div>
      </motion.div>
    </div>
  )
}

export default SettingsModal
