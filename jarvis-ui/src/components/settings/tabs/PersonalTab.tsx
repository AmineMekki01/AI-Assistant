import { useSettings } from '../../../hooks/useSettings'

export function PersonalTab() {
  const settings = useSettings()

  return (
    <div className="tab-content">
      <section className="settings-section">
        <h3>👤 Personal Information</h3>
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
        <h3>🌐 Preferences</h3>

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
    </div>
  )
}
