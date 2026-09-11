import { useState, useEffect, useCallback } from 'react'

interface Reminder {
  id: string
  text: string
  due_at: string
  created_at: string
}

export function RemindersTab() {
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [newText, setNewText] = useState('')
  const [newDelay, setNewDelay] = useState('15 minutes')
  const [loading, setLoading] = useState(false)

  const API_BASE = 'http://localhost:8765'

  const fetchReminders = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/reminders`)
      const data = await resp.json()
      if (data.success) {
        setReminders(data.reminders)
      }
    } catch (e) {
      console.error('Failed to fetch reminders:', e)
    }
  }, [])

  useEffect(() => {
    fetchReminders()
    const interval = setInterval(fetchReminders, 10000)
    return () => clearInterval(interval)
  }, [fetchReminders])

  const handleCreate = async () => {
    if (!newText.trim() || loading) return
    setLoading(true)
    try {
      const resp = await fetch(`${API_BASE}/api/reminders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: newText.trim(), delay: newDelay }),
      })
      const data = await resp.json()
      if (data.success) {
        setNewText('')
        setReminders(prev => [data.reminder, ...prev])
      }
    } catch (e) {
      console.error('Failed to create reminder:', e)
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = async (id: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/reminders/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
      const data = await resp.json()
      if (data.success) {
        setReminders(prev => prev.filter(r => r.id !== id))
      }
    } catch (e) {
      console.error('Failed to cancel reminder:', e)
    }
  }

  const handleSnooze = async (id: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/reminders/snooze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, minutes: 10 }),
      })
      const data = await resp.json()
      if (data.success) {
        fetchReminders()
      }
    } catch (e) {
      console.error('Failed to snooze reminder:', e)
    }
  }

  const formatDue = (iso: string) => {
    try {
      const d = new Date(iso)
      const now = new Date()
      const diffMs = d.getTime() - now.getTime()
      if (diffMs < 0) return 'Overdue'
      const mins = Math.floor(diffMs / 60000)
      if (mins < 60) return `in ${mins} min`
      const hours = Math.floor(mins / 60)
      if (hours < 24) return `in ${hours}h ${mins % 60}m`
      const days = Math.floor(hours / 24)
      return `in ${days}d ${hours % 24}h`
    } catch {
      return iso
    }
  }

  return (
    <div className="tab-content">
      <section className="settings-section">
        <h3>Reminders</h3>
        <p className="settings-description">
          Schedule voice reminders. JARVIS will alert you when they're due.
        </p>

        <div className="quick-notes-input-row">
          <input
            type="text"
            value={newText}
            onChange={e => setNewText(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            placeholder="What to remind you about..."
            className="quick-notes-input"
          />
          <select
            value={newDelay}
            onChange={e => setNewDelay(e.target.value)}
            className="quick-notes-input"
            style={{ width: '140px', flex: 'none' }}
          >
            <option value="5 minutes">5 min</option>
            <option value="15 minutes">15 min</option>
            <option value="30 minutes">30 min</option>
            <option value="1 hour">1 hour</option>
            <option value="2 hours">2 hours</option>
            <option value="1 day">1 day</option>
          </select>
          <button onClick={handleCreate} disabled={loading || !newText.trim()} className="quick-notes-add-btn">
            {loading ? '...' : 'Set'}
          </button>
        </div>

        <div className="quick-notes-list">
          {reminders.length === 0 && (
            <p className="quick-notes-empty">No upcoming reminders. Say "Remind me in 20 minutes..." to create one.</p>
          )}
          {reminders.map(r => (
            <div key={r.id} className="quick-note-item">
              <div className="quick-note-content">
                <span className="quick-note-text">{r.text}</span>
                <span className="quick-note-date">{formatDue(r.due_at)}</span>
              </div>
              <div className="quick-note-actions">
                <button onClick={() => handleSnooze(r.id)} className="quick-note-done" title="Snooze 10 min">
                  Snooze
                </button>
                <button onClick={() => handleCancel(r.id)} className="quick-note-delete" title="Cancel">
                  Cancel
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
