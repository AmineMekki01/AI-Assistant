import { useSettings } from '../../../hooks/useSettings'

export function VoiceTab() {
  const settings = useSettings()

  return (
    <div className="tab-content">
      <section className="settings-section">
        <h3>🎙️ Voice Settings</h3>

        <label className="checkbox toggle">
          <input
            type="checkbox"
            checked={settings.settings.voice.enabled}
            onChange={e => settings.updateVoice({ enabled: e.target.checked })}
          />
          <span className="toggle-slider"></span>
          Enable voice wake word
        </label>

        <div className="form-group">
          <label>Wake Word</label>
          <input
            type="text"
            value={settings.settings.voice.wakeWord}
            onChange={e => settings.updateVoice({ wakeWord: e.target.value })}
            placeholder="Hey JARVIS"
          />
        </div>

        <div className="form-group">
          <label>Wake Word Sensitivity</label>
          <input
            type="range"
            min="0.1"
            max="1"
            step="0.1"
            value={settings.settings.voice.sensitivity}
            onChange={e => settings.updateVoice({ sensitivity: parseFloat(e.target.value) })}
          />
          <span className="range-value">{settings.settings.voice.sensitivity}</span>
        </div>
      </section>
    </div>
  )
}
