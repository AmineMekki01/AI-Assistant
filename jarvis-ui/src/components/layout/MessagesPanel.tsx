import { useEffect, useRef } from 'react'
import { MessageSquare, Sparkles } from 'lucide-react'
import type { Message } from '../../types'

interface MessagesPanelProps { messages: Message[] }

export function MessagesPanel({ messages }: MessagesPanelProps) {
  const list = useRef<HTMLDivElement>(null)
  const follow = useRef(true)
  useEffect(() => {
    if (follow.current && list.current) list.current.scrollTop = list.current.scrollHeight
  }, [messages])
  return (
    <aside className="messages-panel" aria-label="Conversation">
      <div className="panel-header"><MessageSquare size={16} /><h2>Conversation</h2><span className="panel-count">{messages.length.toString().padStart(2, '0')}</span></div>
      <div className="messages-list" ref={list} onScroll={() => { const el = list.current; if (el) follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60 }}>
        {messages.length === 0 ? <div className="empty-state"><span className="empty-icon"><Sparkles size={22} strokeWidth={1.3} /></span><h3>How can I help?</h3><p>Your conversation will appear here.<br />Ask a question, make a plan,<br />or get something done.</p><span className="empty-rule" /><span className="eyebrow">Your voice. Your command.</span></div> : messages.map((msg, i) => <article key={msg.id ?? `${msg.role}-${msg.timestamp.getTime()}-${i}`} className={`message-card ${msg.role}`}><div className="message-role"><span>{msg.role === 'assistant' ? 'Jarvis' : msg.role === 'user' ? 'You' : 'System'}</span><time>{msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div><div className="message-text">{msg.text}</div></article>)}
      </div>
      <div className="panel-footnote">Current session · Conversation history</div>
    </aside>
  )
}
