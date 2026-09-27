import './app.css'
import { MapCanvas } from './map/MapCanvas'

export function App() {
  return <main className="workspace">
    <MapCanvas />
    <aside className="chat-rail" aria-label="Weather chat">
      <header className="chat-heading">
        <span className="wordmark">OpenEPW</span>
        <span className="chat-subtitle">Weather workspace</span>
      </header>
      <div className="chat-transcript" role="log" aria-live="polite">
        <div className="welcome">Where do you need weather?</div>
      </div>
      <form className="composer" onSubmit={event => event.preventDefault()}>
        <label htmlFor="chat-message">Message</label>
        <div className="composer-row">
          <input id="chat-message" name="message" placeholder="Place, years, and weather type" />
          <button type="submit">Send</button>
        </div>
      </form>
    </aside>
  </main>
}
