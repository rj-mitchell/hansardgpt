import { useState } from "react";
import { api } from "../api";
import { ATTRIBUTION } from "../attribution";

export function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(email, password);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <div className="cover" aria-hidden="true">
        <p className="cover-kicker">Parliamentary Debates</p>
        <p className="cover-title">HansardGPT</p>
        <p className="cover-years">Sourced briefings since 2010</p>
      </div>
      <form onSubmit={submit} className="login-card" aria-label="Sign in">
        <h1>Sign in to HansardGPT</h1>
        <p className="muted">Briefings on what Parliament has said. Every claim is cited to Hansard.</p>
        <label>
          Email
          <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="muted small">Accounts are by invitation. Ask the administrator for access.</p>
      </form>
      <footer className="footer">
        {ATTRIBUTION.map((a) => (
          <a key={a.url} href={a.url} target="_blank" rel="noreferrer">
            {a.text}
          </a>
        ))}
      </footer>
    </main>
  );
}
