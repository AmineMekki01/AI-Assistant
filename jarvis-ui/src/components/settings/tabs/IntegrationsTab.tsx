import { useState, useEffect, useCallback } from 'react'
import { useSettings } from '../../../hooks/useSettings'

export function IntegrationsTab() {
  const settings = useSettings()
  const {
    checkDashboardHealth,
    listAppleCalendars,
    disconnectGoogle,
    initiateGoogleAuth,
    testQdrantConnection,
    bootstrapQdrant: createQdrantCollection,
    syncObsidian: runObsidianSync,
    checkQdrantStatus,
    checkObsidianStatus,
    testZimbraConnection,
    checkZimbraStatus,
    testAppleCalendar,
    checkAppleCalendarStatus,
  } = settings
  const [dashboardHealth, setDashboardHealth] = useState<Awaited<ReturnType<typeof settings.checkDashboardHealth>> | null>(null)
  const [qdrantStatus, setQdrantStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle')
  const [obsidianStatus, setObsidianStatus] = useState<'idle' | 'syncing' | 'success' | 'error'>('idle')
  const [googleStatus, setGoogleStatus] = useState<{connected: boolean, lastConnected?: number} | null>(null)
  const [qdrantDetails, setQdrantDetails] = useState<{connected: boolean, lastChecked?: number | null, collectionExists?: boolean} | null>(null)
  const [obsidianDetails, setObsidianDetails] = useState<{synced: boolean, lastSync?: number | null, fileCount?: number} | null>(null)
  const [zimbraStatus, setZimbraStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle')
  const [zimbraDetails, setZimbraDetails] = useState<{configured: boolean, lastTested?: number | null, ok?: boolean | null} | null>(null)
  const [zimbraError, setZimbraError] = useState<string | null>(null)
  const [appleCalStatus, setAppleCalStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle')
  const [appleCalDetails, setAppleCalDetails] = useState<{enabled: boolean, available: boolean, lastTested?: number | null, ok?: boolean | null} | null>(null)
  const [appleCalError, setAppleCalError] = useState<string | null>(null)
  const [appleCalendars, setAppleCalendars] = useState<string[]>([])
  const [syncResult, setSyncResult] = useState<{totalFiles?: number, indexed?: number, qdrantStatus?: string} | null>(null)

  const dashboardOnlineCount = dashboardHealth
    ? [
        dashboardHealth.google.connected,
        dashboardHealth.qdrant.connected,
        dashboardHealth.obsidian.synced,
        dashboardHealth.zimbra.ok === true,
        dashboardHealth.appleCalendar.ok === true,
        dashboardHealth.music.available,
      ].filter(Boolean).length
    : 0
  const dashboardTotalCount = 6

  const refreshDashboard = useCallback(async () => {
    const [health, calendars] = await Promise.all([
      checkDashboardHealth(),
      listAppleCalendars(),
    ])

    if (health) {
      setDashboardHealth(health)
      setGoogleStatus({ connected: health.google.connected, lastConnected: health.google.lastConnected ?? undefined })
      setQdrantDetails(health.qdrant)
      setQdrantStatus(health.qdrant.connected ? 'success' : 'idle')
      setObsidianDetails(health.obsidian)
      setObsidianStatus(health.obsidian.synced ? 'success' : 'idle')
      setZimbraDetails(health.zimbra)
      if (health.zimbra.ok === true) setZimbraStatus('success')
      else if (health.zimbra.ok === false) setZimbraStatus('error')
      else setZimbraStatus('idle')
      setAppleCalDetails(health.appleCalendar)
      if (health.appleCalendar.ok === true) setAppleCalStatus('success')
      else if (health.appleCalendar.ok === false) setAppleCalStatus('error')
      else setAppleCalStatus('idle')
    }

    if (calendars.length > 0) {
      setAppleCalendars(calendars)
    }
  }, [checkDashboardHealth, listAppleCalendars])

  useEffect(() => {
    refreshDashboard()
  }, [refreshDashboard])

  const testZimbra = async () => {
    setZimbraStatus('testing')
    setZimbraError(null)
    const result = await testZimbraConnection()
    setZimbraStatus(result.ok ? 'success' : 'error')
    setZimbraError(result.ok ? null : result.error || 'Connection failed')
    const status = await checkZimbraStatus()
    if (status) setZimbraDetails(status)
  }

  const testAppleCal = async () => {
    setAppleCalStatus('testing')
    setAppleCalError(null)
    const result = await testAppleCalendar()
    setAppleCalStatus(result.ok ? 'success' : 'error')
    setAppleCalError(result.ok ? null : result.error || 'Apple Calendar permission denied')
    const status = await checkAppleCalendarStatus()
    if (status) setAppleCalDetails(status)
    if (result.ok) {
      const names = await listAppleCalendars()
      setAppleCalendars(names)
    }
  }

  const testQdrant = async () => {
    setQdrantStatus('testing')
    const ok = await testQdrantConnection()
    setQdrantStatus(ok ? 'success' : 'error')
    const status = await checkQdrantStatus()
    if (status) setQdrantDetails(status)
    if (ok) {
      await refreshDashboard()
    }
  }

  const bootstrapQdrant = async () => {
    setQdrantStatus('testing')
    const ok = await createQdrantCollection()
    setQdrantStatus(ok ? 'success' : 'error')
    await refreshDashboard()
  }

  const syncObsidian = async () => {
    setObsidianStatus('syncing')
    setSyncResult(null)
    const result = await runObsidianSync()
    setObsidianStatus(result ? 'success' : 'error')
    if (result && typeof result === 'object') {
      setSyncResult(result)
    }
    const status = await checkObsidianStatus()
    if (status) setObsidianDetails(status)
    await refreshDashboard()
  }

  const handleGoogleToggle = async () => {
    if (googleStatus?.connected) {
      await disconnectGoogle()
    } else {
      initiateGoogleAuth()
      return
    }

    await refreshDashboard()
  }

  return (
    <div className="tab-content">
      <section className="settings-section dashboard-section">
        <div className="dashboard-hero">
          <div>
            <p className="dashboard-eyebrow">Control center</p>
            <h3>🩺 Connections &amp; Integrations</h3>
            <p className="section-desc">
              Live backend and integration status at a glance. Use this to see what is connected,
              what is ready, and what still needs attention.
            </p>
          </div>

          <div className="dashboard-summary-card">
            <div className="dashboard-summary-count">{dashboardOnlineCount}/{dashboardTotalCount}</div>
            <div className="dashboard-summary-label">services ready</div>
            <span className={`status-badge ${dashboardHealth?.status === 'ok' ? 'success' : 'idle'}`}>
              {dashboardHealth?.status === 'ok' ? 'Live snapshot' : 'Refreshing...'}
            </span>
          </div>
        </div>

        <div className="status-grid dashboard-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
          <div className="status-item"><span className="status-label">Backend</span><span className={`status-value ${dashboardHealth?.status === 'ok' ? 'active' : ''}`}>{dashboardHealth?.status === 'ok' ? 'ONLINE' : 'CHECKING'}</span></div>
          <div className="status-item"><span className="status-label">Google</span><span className={`status-value ${dashboardHealth?.google.connected ? 'active' : ''}`}>{dashboardHealth?.google.connected ? 'CONNECTED' : 'DISCONNECTED'}</span></div>
          <div className="status-item"><span className="status-label">Qdrant</span><span className={`status-value ${dashboardHealth?.qdrant.connected ? 'active' : ''}`}>{dashboardHealth?.qdrant.connected ? 'CONNECTED' : 'DISCONNECTED'}</span></div>
          <div className="status-item"><span className="status-label">Obsidian</span><span className={`status-value ${dashboardHealth?.obsidian.synced ? 'active' : ''}`}>{dashboardHealth?.obsidian.synced ? 'SYNCED' : 'NOT SYNCED'}</span></div>
          <div className="status-item"><span className="status-label">Zimbra</span><span className={`status-value ${dashboardHealth?.zimbra.ok === true ? 'active' : ''}`}>{dashboardHealth?.zimbra.ok === true ? 'CONNECTED' : 'NOT TESTED'}</span></div>
          <div className="status-item"><span className="status-label">Apple Calendar</span><span className={`status-value ${dashboardHealth?.appleCalendar.ok === true ? 'active' : ''}`}>{dashboardHealth?.appleCalendar.ok === true ? 'AVAILABLE' : 'NOT TESTED'}</span></div>
          <div className="status-item"><span className="status-label">Music</span><span className={`status-value ${dashboardHealth?.music.available ? 'active' : ''}`}>{dashboardHealth?.music.available ? `${dashboardHealth.music.librarySize} TRACKS` : 'UNAVAILABLE'}</span></div>
        </div>

        <div className="button-group">
          <button className="btn-secondary" onClick={refreshDashboard}>
            Refresh All
          </button>
        </div>
      </section>

      <section className="settings-section qdrant-section">
        <div className="section-header">
          <h3>🗄️ Qdrant Vector Database</h3>
          <span className={`status-badge ${qdrantStatus}`}>
            {qdrantStatus === 'idle' && 'Not Tested'}
            {qdrantStatus === 'testing' && 'Testing...'}
            {qdrantStatus === 'success' && 'Connected'}
            {qdrantStatus === 'error' && 'Needs Attention'}
          </span>
        </div>
        <p className="section-desc">Configure the vector store that powers memory and knowledge retrieval.</p>

        {qdrantDetails?.lastChecked && (
          <p className="last-sync">
            Last checked: {new Date(qdrantDetails.lastChecked * 1000).toLocaleString()}
            {qdrantDetails.collectionExists && ' • Collection exists'}
          </p>
        )}

        <div className="form-grid">
          <div className="form-group">
            <label>Host</label>
            <input
              type="text"
              value={settings.settings.qdrant.host}
              onChange={e => settings.updateQdrant({ host: e.target.value })}
              placeholder="localhost"
            />
          </div>
          <div className="form-group">
            <label>Port</label>
            <input
              type="number"
              value={settings.settings.qdrant.port}
              onChange={e => settings.updateQdrant({ port: parseInt(e.target.value) })}
            />
          </div>
        </div>

        <div className="form-group">
          <label>Collection Name</label>
          <input
            type="text"
            value={settings.settings.qdrant.collectionName}
            onChange={e => settings.updateQdrant({ collectionName: e.target.value })}
            placeholder="jarvis_knowledge"
          />
        </div>

        <div className="form-group">
          <label>API Key (optional)</label>
          <input
            type="password"
            value={settings.settings.qdrant.apiKey || ''}
            onChange={e => settings.updateQdrant({ apiKey: e.target.value })}
            placeholder="For cloud Qdrant instances"
          />
        </div>

        <div className="button-group">
          <button className="btn-secondary" onClick={testQdrant} disabled={qdrantStatus === 'testing'}>
            {qdrantStatus === 'testing' ? 'Testing...' : 'Test Connection'}
          </button>
          <button className="btn-primary" onClick={bootstrapQdrant} disabled={qdrantStatus === 'testing'}>
            Create Collection
          </button>
        </div>

        {qdrantStatus === 'error' && settings.error && (
          <div className="error-message">Qdrant test failed: {settings.error}</div>
        )}
      </section>

      <section className="settings-section obsidian-section">
        <div className="section-header">
          <h3>📝 Obsidian Vault</h3>
          <span className={`status-badge ${obsidianStatus}`}>
            {obsidianStatus === 'idle' && 'Not Synced'}
            {obsidianStatus === 'syncing' && 'Syncing...'}
            {obsidianStatus === 'success' && 'Synced'}
            {obsidianStatus === 'error' && 'Failed'}
          </span>
        </div>
        <p className="section-desc">Index your Obsidian vault for knowledge search</p>

        {obsidianDetails?.synced && obsidianDetails.lastSync && (
          <p className="last-sync">
            Last synced: {new Date(obsidianDetails.lastSync * 1000).toLocaleString()}
            {obsidianDetails.fileCount !== undefined && ` • ${obsidianDetails.fileCount} files indexed`}
          </p>
        )}

        <div className="form-group">
          <label>Vault Path</label>
          <input
            type="text"
            value={settings.settings.obsidian.vaultPath}
            onChange={e => settings.updateObsidian({ vaultPath: e.target.value })}
            placeholder="/Users/username/Documents/Obsidian Vault"
          />
        </div>

        <div className="form-row">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={settings.settings.obsidian.enabled}
              onChange={e => settings.updateObsidian({ enabled: e.target.checked })}
            />
            Enable Obsidian integration
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={settings.settings.obsidian.autoSync}
              onChange={e => settings.updateObsidian({ autoSync: e.target.checked })}
            />
            Auto-sync every {settings.settings.obsidian.syncInterval} minutes
          </label>
        </div>

        <div className="button-group">
          <button
            className="btn-primary"
            onClick={syncObsidian}
            disabled={!settings.settings.obsidian.vaultPath || obsidianStatus === 'syncing'}
          >
            {obsidianStatus === 'syncing' ? 'Syncing...' : 'Sync Now'}
          </button>
        </div>

        {syncResult && (
          <div className="sync-result">
            <p><strong>✅ Sync Complete!</strong></p>
            <p>Files found: {syncResult?.totalFiles ?? 0}</p>
            <p>Files indexed: {syncResult?.indexed ?? 0}</p>
            <p>Vector DB: {syncResult?.qdrantStatus ?? 'unknown'}</p>
          </div>
        )}
      </section>

      <section className="settings-section google-section">
        <div className="section-header">
          <h3>📧 Google Integration</h3>
          <span className={`status-badge ${googleStatus?.connected ? 'success' : 'idle'}`}>
            {googleStatus?.connected ? 'Connected' : 'Not Connected'}
          </span>
        </div>
        <p className="section-desc">Connect Gmail and Google Calendar for email and scheduling features</p>

        {googleStatus?.connected && googleStatus.lastConnected && (
          <p className="last-sync">
            Last connected: {new Date(googleStatus.lastConnected * 1000).toLocaleString()}
          </p>
        )}

        <div className="form-group">
          <label>OAuth Client ID</label>
          <input
            type="text"
            value={settings.settings.google.clientId}
            onChange={e => settings.updateGoogle({ clientId: e.target.value })}
            placeholder="your-client-id.apps.googleusercontent.com"
          />
        </div>

        <div className="form-group">
          <label>Redirect URI</label>
          <input
            type="text"
            value={settings.settings.google.redirectUri}
            onChange={e => settings.updateGoogle({ redirectUri: e.target.value })}
            placeholder="http://localhost:8001/auth/callback"
          />
        </div>

        <div className="form-row">
          <label className="checkbox">
            <input type="checkbox" checked disabled />
            Gmail (Read & Send)
          </label>
          <label className="checkbox">
            <input type="checkbox" checked disabled />
            Calendar
          </label>
        </div>

        <div className="button-group">
          {!googleStatus?.connected ? (
            <button
              className="btn-primary"
              onClick={handleGoogleToggle}
              disabled={!settings.settings.google.clientId}
            >
              {settings.settings.google.enabled ? 'Reconnect Google Account' : 'Connect Google Account'}
            </button>
          ) : (
            <button className="btn-danger" onClick={handleGoogleToggle}>
              Disconnect
            </button>
          )}
          <button className="btn-secondary" onClick={refreshDashboard}>
            Refresh Status
          </button>
        </div>

        <div className="info-box">
          <p>To set up Google OAuth:</p>
          <ol>
            <li>Go to <a href="https://console.cloud.google.com" target="_blank" rel="noreferrer">Google Cloud Console</a></li>
            <li>Create a project and enable Gmail & Calendar APIs</li>
            <li>Configure OAuth consent screen</li>
            <li>Create OAuth 2.0 credentials (Web application)</li>
            <li>Add redirect URI: {settings.settings.google.redirectUri}</li>
          </ol>
        </div>
      </section>

      <section className="settings-section zimbra-section">
        <div className="section-header">
          <h3>✉️ Secondary Mailbox (Zimbra / OVH / IMAP)</h3>
          <span className={`status-badge ${zimbraStatus}`}>
            {zimbraStatus === 'idle' && 'Not Configured'}
            {zimbraStatus === 'testing' && 'Testing...'}
            {zimbraStatus === 'success' && 'Connected'}
            {zimbraStatus === 'error' && 'Failed'}
          </span>
        </div>
        <p className="section-desc">
          Connect a non-Google mailbox over IMAP (read) and SMTP (send). Works with OVH Mail Pro,
          Zimbra, and any standard IMAP provider.
        </p>

        {zimbraDetails?.lastTested && (
          <p className="last-sync">
            Last tested: {new Date(zimbraDetails.lastTested * 1000).toLocaleString()}
            {zimbraDetails.ok === true && ' • Authenticated'}
            {zimbraDetails.ok === false && ' • Authentication failed'}
          </p>
        )}

        <div className="form-row">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={settings.settings.zimbra.enabled}
              onChange={e => settings.updateZimbra({ enabled: e.target.checked })}
            />
            Enable secondary mailbox
          </label>
        </div>

        <div className="form-group">
          <label>Email address</label>
          <input
            type="email"
            value={settings.settings.zimbra.email}
            onChange={e => settings.updateZimbra({ email: e.target.value })}
            placeholder="you@yourdomain.com"
            disabled={!settings.settings.zimbra.enabled}
          />
        </div>

        <div className="form-group">
          <label>Password (or app password)</label>
          <input
            type="password"
            value={settings.settings.zimbra.password}
            onChange={e => settings.updateZimbra({ password: e.target.value })}
            placeholder="••••••••"
            autoComplete="new-password"
            disabled={!settings.settings.zimbra.enabled}
          />
        </div>

        <div className="form-grid">
          <div className="form-group">
            <label>IMAP host</label>
            <input
              type="text"
              value={settings.settings.zimbra.imapHost}
              onChange={e => settings.updateZimbra({ imapHost: e.target.value })}
              placeholder="ssl0.ovh.net"
              disabled={!settings.settings.zimbra.enabled}
            />
          </div>
          <div className="form-group">
            <label>IMAP port</label>
            <input
              type="number"
              value={settings.settings.zimbra.imapPort}
              onChange={e => settings.updateZimbra({ imapPort: parseInt(e.target.value) || 993 })}
              disabled={!settings.settings.zimbra.enabled}
            />
          </div>
        </div>

        <div className="form-grid">
          <div className="form-group">
            <label>SMTP host</label>
            <input
              type="text"
              value={settings.settings.zimbra.smtpHost}
              onChange={e => settings.updateZimbra({ smtpHost: e.target.value })}
              placeholder="ssl0.ovh.net"
              disabled={!settings.settings.zimbra.enabled}
            />
          </div>
          <div className="form-group">
            <label>SMTP port</label>
            <input
              type="number"
              value={settings.settings.zimbra.smtpPort}
              onChange={e => settings.updateZimbra({ smtpPort: parseInt(e.target.value) || 465 })}
              disabled={!settings.settings.zimbra.enabled}
            />
          </div>
        </div>

        <div className="form-row">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={settings.settings.zimbra.smtpSsl}
              onChange={e => settings.updateZimbra({ smtpSsl: e.target.checked })}
              disabled={!settings.settings.zimbra.enabled}
            />
            Use implicit SSL for SMTP (port 465). Uncheck for STARTTLS on port 587.
          </label>
        </div>

        <div className="button-group">
          <button
            className="btn-primary"
            onClick={testZimbra}
            disabled={
              !settings.settings.zimbra.enabled ||
              !settings.settings.zimbra.email ||
              !settings.settings.zimbra.password ||
              zimbraStatus === 'testing'
            }
          >
            {zimbraStatus === 'testing' ? 'Testing...' : 'Test & Save Connection'}
          </button>
        </div>

        {zimbraError && <div className="error-message">{zimbraError}</div>}

        <div className="info-box">
          <p><strong>OVH Mail Pro defaults:</strong></p>
          <ul>
            <li>IMAP: <code>ssl0.ovh.net</code> : <code>993</code> (SSL)</li>
            <li>SMTP: <code>ssl0.ovh.net</code> : <code>465</code> (SSL)</li>
            <li>If your OVH account has 2FA enabled, generate an app password in the OVH Manager.</li>
          </ul>
          <p style={{ marginTop: 8 }}>
            Credentials are saved locally to <code>~/.jarvis/settings.json</code>. Nothing is sent
            to any third-party service.
          </p>
        </div>
      </section>

      {/* Apple Calendar Section */}
      <section className="settings-section apple-calendar-section">
        <div className="section-header">
          <h3>🗓️ Apple Calendar (macOS)</h3>
          <span className={`status-badge ${appleCalStatus}`}>
            {appleCalStatus === 'idle' && (appleCalDetails?.available === false ? 'macOS only' : 'Not Tested')}
            {appleCalStatus === 'testing' && 'Probing...'}
            {appleCalStatus === 'success' && 'Connected'}
            {appleCalStatus === 'error' && 'Failed'}
          </span>
        </div>
        <p className="section-desc">
          Read and write events in the macOS Calendar.app. Useful when you keep iCloud-only,
          shared-family, subscribed, or Exchange calendars that aren't synced to Google.
        </p>

        {appleCalDetails?.lastTested && (
          <p className="last-sync">
            Last probed: {new Date(appleCalDetails.lastTested * 1000).toLocaleString()}
            {appleCalDetails.ok === true && ' • macOS permission granted'}
            {appleCalDetails.ok === false && ' • permission denied'}
          </p>
        )}

        <div className="form-row">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={settings.settings.appleCalendar.enabled}
              onChange={e => settings.updateAppleCalendar({ enabled: e.target.checked })}
              disabled={appleCalDetails?.available === false}
            />
            Enable Apple Calendar access
          </label>
        </div>

        <div className="form-group">
          <label>Default calendar for new events</label>
          {appleCalendars.length > 0 ? (
            <select
              value={settings.settings.appleCalendar.defaultCalendar}
              onChange={e => settings.updateAppleCalendar({ defaultCalendar: e.target.value })}
              disabled={!settings.settings.appleCalendar.enabled}
            >
              <option value="">(First writable calendar)</option>
              {appleCalendars.map(name => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={settings.settings.appleCalendar.defaultCalendar}
              onChange={e => settings.updateAppleCalendar({ defaultCalendar: e.target.value })}
              placeholder="e.g. Home, Work, Family - or leave blank"
              disabled={!settings.settings.appleCalendar.enabled}
            />
          )}
        </div>

        <div className="button-group">
          <button
            className="btn-primary"
            onClick={testAppleCal}
            disabled={
              !settings.settings.appleCalendar.enabled ||
              appleCalDetails?.available === false ||
              appleCalStatus === 'testing'
            }
          >
            {appleCalStatus === 'testing' ? 'Probing...' : 'Test & Request Permission'}
          </button>
        </div>

        {appleCalError && <div className="error-message">{appleCalError}</div>}

        <div className="info-box">
          <p><strong>How this works:</strong></p>
          <ul>
            <li>JARVIS talks to Calendar.app via AppleScript - no cloud credentials needed.</li>
            <li>The first probe will trigger a macOS prompt asking you to allow Calendar access to the app running JARVIS (Terminal / VS Code / iTerm / the JARVIS app itself).</li>
            <li>You can revoke access anytime in <em>System Settings → Privacy & Security → Calendars</em>.</li>
            <li>Only works on macOS. On other systems this integration is disabled.</li>
          </ul>
        </div>
      </section>
    </div>
  )
}
