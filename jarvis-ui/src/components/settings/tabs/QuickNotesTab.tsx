import { useState, useEffect, useCallback } from 'react'

interface QuickNote {
  id: string
  text: string
  created_at: string
  done: boolean
}

export function QuickNotesTab() {
  const [notes, setNotes] = useState<QuickNote[]>([])
  const [newNote, setNewNote] = useState('')
  const [loading, setLoading] = useState(false)

  const API_BASE = 'http://localhost:8765'

  const fetchNotes = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/quick_notes`)
      const data = await resp.json()
      if (data.success) {
        setNotes(data.notes)
      }
    } catch (e) {
      console.error('Failed to fetch quick notes:', e)
    }
  }, [])

  useEffect(() => {
    fetchNotes()
    const interval = setInterval(fetchNotes, 10000)
    return () => clearInterval(interval)
  }, [fetchNotes])

  const handleCreate = async () => {
    if (!newNote.trim() || loading) return
    setLoading(true)
    try {
      const resp = await fetch(`${API_BASE}/api/quick_notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: newNote.trim() }),
      })
      const data = await resp.json()
      if (data.success) {
        setNewNote('')
        setNotes(prev => [data.note, ...prev])
      }
    } catch (e) {
      console.error('Failed to create note:', e)
    } finally {
      setLoading(false)
    }
  }

  const handleDone = async (id: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/quick_notes/done`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
      const data = await resp.json()
      if (data.success) {
        setNotes(prev => prev.filter(n => n.id !== id))
      }
    } catch (e) {
      console.error('Failed to mark note done:', e)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/quick_notes/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
      const data = await resp.json()
      if (data.success) {
        setNotes(prev => prev.filter(n => n.id !== id))
      }
    } catch (e) {
      console.error('Failed to delete note:', e)
    }
  }

  const formatDate = (iso: string) => {
    try {
      const d = new Date(iso)
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    } catch {
      return iso
    }
  }

  return (
    <div className="tab-content">
      <section className="settings-section">
        <h3>Quick Notes</h3>
        <p className="settings-description">
          Voice memos and quick captures auto-appear here. They expire after 7 days.
        </p>

        <div className="quick-notes-input-row">
          <input
            type="text"
            value={newNote}
            onChange={e => setNewNote(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            placeholder="Type a quick note..."
            className="quick-notes-input"
          />
          <button onClick={handleCreate} disabled={loading || !newNote.trim()} className="quick-notes-add-btn">
            {loading ? '...' : 'Add'}
          </button>
        </div>

        <div className="quick-notes-list">
          {notes.length === 0 && (
            <p className="quick-notes-empty">No pending notes. Say "JARVIS, note that..." to capture one.</p>
          )}
          {notes.map(note => (
            <div key={note.id} className="quick-note-item">
              <div className="quick-note-content">
                <span className="quick-note-text">{note.text}</span>
                <span className="quick-note-date">{formatDate(note.created_at)}</span>
              </div>
              <div className="quick-note-actions">
                <button onClick={() => handleDone(note.id)} className="quick-note-done" title="Mark done">
                  Done
                </button>
                <button onClick={() => handleDelete(note.id)} className="quick-note-delete" title="Delete">
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
