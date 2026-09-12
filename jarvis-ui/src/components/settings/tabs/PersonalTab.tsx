import { useState } from 'react'
import { useSettings } from '../../../hooks/useSettings'

interface EmailTemplate {
  name: string
  subject: string
  body: string
}

export function PersonalTab() {
  const settings = useSettings()
  const [templateName, setTemplateName] = useState('')
  const [templateSubject, setTemplateSubject] = useState('')
  const [templateBody, setTemplateBody] = useState('')

  const templates: EmailTemplate[] = (settings.settings as any).templates
    ? Object.entries((settings.settings as any).templates).map(([name, t]) => ({
        name,
        subject: (t as any).subject || '',
        body: (t as any).body || '',
      }))
    : []

  const handleSaveTemplate = () => {
    if (!templateName.trim() || !templateSubject.trim() || !templateBody.trim()) return
    const updated = {
      ...(settings.settings as any).templates,
      [templateName.trim()]: { subject: templateSubject.trim(), body: templateBody.trim() },
    }
    ;(settings.settings as any).templates = updated
    settings.saveSettings()
    setTemplateName('')
    setTemplateSubject('')
    setTemplateBody('')
  }

  const handleDeleteTemplate = (name: string) => {
    const current = { ...(settings.settings as any).templates }
    delete current[name]
    ;(settings.settings as any).templates = current
    settings.saveSettings()
  }

  return (
    <div className="tab-content">
      <section className="settings-section">
        <h3>Personal Information</h3>
        <p className="section-desc">Your personal details help JARVIS provide better assistance</p>

        <div className="form-grid">
          <div className="form-group">
            <label>Name</label>
            <input
              type="text"
              value={settings.settings.personal.name}
              onChange={e => settings.updatePersonal({ name: e.target.value })}
              placeholder="Tony"
            />
          </div>
          <div className="form-group">
            <label>Email</label>
            <input
              type="email"
              value={settings.settings.personal.email}
              onChange={e => settings.updatePersonal({ email: e.target.value })}
              placeholder="tony@stark.com"
            />
          </div>
        </div>

        <div className="form-group">
          <label>Timezone</label>
          <select
            value={settings.settings.personal.timezone}
            onChange={e => settings.updatePersonal({ timezone: e.target.value })}
          >
            <option value="UTC">UTC</option>
            <option value="America/New_York">Eastern Time (ET)</option>
            <option value="America/Chicago">Central Time (CT)</option>
            <option value="America/Denver">Mountain Time (MT)</option>
            <option value="America/Los_Angeles">Pacific Time (PT)</option>
            <option value="Europe/London">London (GMT)</option>
            <option value="Europe/Paris">Paris (CET)</option>
            <option value="Europe/Berlin">Berlin (CET)</option>
            <option value="Asia/Tokyo">Tokyo (JST)</option>
            <option value="Asia/Shanghai">Shanghai (CST)</option>
            <option value="Asia/Dubai">Dubai (GST)</option>
            <option value="Australia/Sydney">Sydney (AEDT)</option>
            <option value="Pacific/Auckland">Auckland (NZDT)</option>
          </select>
        </div>

        <div className="form-group">
          <label>Default Location</label>
          <input
            type="text"
            value={settings.settings.personal.defaultLocation}
            onChange={e => settings.updatePersonal({ defaultLocation: e.target.value })}
            placeholder="New York, NY"
          />
        </div>
      </section>

      <section className="settings-section">
        <h3>Preferences</h3>

        <div className="form-row">
          <div className="form-group">
            <label>Temperature Unit</label>
            <select
              value={settings.settings.personal.preferences.temperatureUnit}
              onChange={e => settings.updatePersonal({
                preferences: { ...settings.settings.personal.preferences, temperatureUnit: e.target.value as 'celsius' | 'fahrenheit' }
              })}
            >
              <option value="celsius">Celsius (°C)</option>
              <option value="fahrenheit">Fahrenheit (°F)</option>
            </select>
          </div>

          <div className="form-group">
            <label>Time Format</label>
            <select
              value={settings.settings.personal.preferences.timeFormat}
              onChange={e => settings.updatePersonal({
                preferences: { ...settings.settings.personal.preferences, timeFormat: e.target.value as '12h' | '24h' }
              })}
            >
              <option value="12h">12-hour (AM/PM)</option>
              <option value="24h">24-hour</option>
            </select>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <h3>Email Templates</h3>
        <p className="section-desc">Save reusable email drafts with {'{'}placeholder{'}'} variables</p>

        <div className="form-grid">
          <div className="form-group">
            <label>Template Name</label>
            <input
              type="text"
              value={templateName}
              onChange={e => setTemplateName(e.target.value)}
              placeholder="meeting-follow-up"
            />
          </div>
          <div className="form-group">
            <label>Subject</label>
            <input
              type="text"
              value={templateSubject}
              onChange={e => setTemplateSubject(e.target.value)}
              placeholder="Follow-up: {{topic}}"
            />
          </div>
        </div>
        <div className="form-group">
          <label>Body</label>
          <textarea
            value={templateBody}
            onChange={e => setTemplateBody(e.target.value)}
            placeholder="Hi {{name}}, thanks for the meeting about {{topic}}..."
            rows={4}
            style={{ width: '100%', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '10px', color: 'var(--text-primary)', fontSize: '14px' }}
          />
        </div>
        <div className="button-group">
          <button className="btn-primary" onClick={handleSaveTemplate}>Save Template</button>
        </div>

        {templates.length > 0 && (
          <div className="quick-notes-list" style={{ marginTop: '16px' }}>
            {templates.map(t => (
              <div key={t.name} className="quick-note-item">
                <div className="quick-note-content">
                  <span className="quick-note-text">{t.name}</span>
                  <span className="quick-note-date">{t.subject}</span>
                </div>
                <div className="quick-note-actions">
                  <button onClick={() => handleDeleteTemplate(t.name)} className="quick-note-delete">Delete</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
