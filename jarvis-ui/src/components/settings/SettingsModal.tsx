import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Aperture, AudioLines, Bell, Info, FileText, Plug, UserRound, X, ChevronRight } from 'lucide-react'
import { IntegrationsTab, PersonalTab, VoiceTab, AboutTab, QuickNotesTab, RemindersTab } from './tabs'
import './SettingsModal.css'

const sections = [
  { id: 'integrations', label: 'Integrations', description: 'Connect the tools that make your day easier.', icon: Plug, component: IntegrationsTab },
  { id: 'personal', label: 'Personal', description: 'The details that make JARVIS feel like yours.', icon: UserRound, component: PersonalTab },
  { id: 'voice', label: 'Voice', description: 'A conversation that feels natural to you.', icon: AudioLines, component: VoiceTab },
  { id: 'quick_notes', label: 'Notes', description: 'Keep a thought. Come back to it later.', icon: FileText, component: QuickNotesTab },
  { id: 'reminders', label: 'Reminders', description: 'A little help remembering what matters.', icon: Bell, component: RemindersTab },
  { id: 'about', label: 'About', description: 'Meet your personal assistant.', icon: Info, component: AboutTab },
] as const

interface SettingsModalProps { onClose: () => void }

export function SettingsModal({ onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<string>('integrations')
  const dialog = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  close.current = onClose
  const section = sections.find(tab => tab.id === activeTab) ?? sections[0]
  const Content = section.component

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null
    dialog.current?.focus()
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close.current(); return }
      if (event.key !== 'Tab') return
      const elements = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]') ?? []).filter(el => el.getClientRects().length > 0)
      const first = elements[0]
      const last = elements[elements.length - 1]
      if (!first) { event.preventDefault(); return }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', handleKey)
    return () => { document.removeEventListener('keydown', handleKey); previousFocus?.focus() }
  }, [])

  useEffect(() => { content.current?.scrollTo(0, 0) }, [activeTab])

  return (
    <div className="settings-modal-overlay" onClick={onClose}>
      <motion.div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="settings-title" tabIndex={-1} className="settings-modal" onClick={e => e.stopPropagation()} initial={{ opacity: 0, y: 12, scale: 0.99 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }} transition={{ duration: 0.18 }}>
        <div className="settings-header"><div><p className="eyebrow">System preferences</p><h2 id="settings-title">Settings</h2></div><button className="close-btn" onClick={onClose} aria-label="Close settings"><X size={19} /></button></div>
        <div className="settings-body">
          <nav className="settings-tabs" aria-label="Settings sections">
            <span className="settings-nav-label">Workspace</span>
            {sections.map(({ id, label, icon: Icon }) => <button key={id} className={activeTab === id ? 'active' : ''} aria-current={activeTab === id ? 'page' : undefined} onClick={() => setActiveTab(id)}><Icon size={17} strokeWidth={1.6} /><span>{label}</span><ChevronRight className="nav-chevron" size={14} /></button>)}
            <div className="settings-signature"><Aperture size={22} strokeWidth={1.2} /><span>Personal intelligence.<strong>JARVIS</strong></span></div>
          </nav>
          <div className="settings-content" ref={content}>
            <div className="settings-page-heading"><h3>{section.label}</h3><p>{section.description}</p></div>
            <Content />
          </div>
        </div>
      </motion.div>
    </div>
  )
}

export default SettingsModal
