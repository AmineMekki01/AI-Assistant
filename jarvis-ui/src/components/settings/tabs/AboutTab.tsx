import { Aperture } from 'lucide-react'

export function AboutTab() {
  return (
    <div className="tab-content">
      <section className="settings-section about">
        <div className="about-logo"><Aperture size={58} strokeWidth={1} /></div>
        <h2>J.A.R.V.I.S.</h2>
        <p className="version">Version 2.0.0</p>
        <p className="tagline">Just A Rather Very Intelligent System</p>

        <div className="about-credits">
          <p>Voice, intelligence, and your everyday tools. Connected.</p>
          <div className="tech-stack">
            <span>React</span>
            <span>TypeScript</span>
            <span>Vite</span>
            <span>Python</span>
            <span>OpenAI</span>
            <span>Qdrant</span>
          </div>
        </div>
      </section>
    </div>
  )
}
