import { Aperture, Settings2 } from 'lucide-react'
import { StatusBadge } from '../ui/StatusBadge'
import type { ConnectionState } from '../../types'

interface HeaderProps {
  status: ConnectionState
  isRecording: boolean
  isSpeaking: boolean
  onOpenSettings: () => void
}

export function Header({ status, isRecording, isSpeaking, onOpenSettings }: HeaderProps) {
  return (
    <header className="jarvis-header">
      <div className="brand"><span className="brand-mark"><Aperture size={25} strokeWidth={1.3} /></span><div className="header-left"><span className="logo">JARVIS<span className="brand-period">.</span></span><span className="subtitle">Your personal assistant</span></div></div>
      <div className="header-actions">
        <StatusBadge status={status} isRecording={isRecording} isSpeaking={isSpeaking} />
        <span className="header-divider" />
        <button className="settings-trigger" onClick={onOpenSettings}><Settings2 size={17} /><span>Settings</span></button>
      </div>
    </header>
  )
}
