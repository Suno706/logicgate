/**
 * Sign-in / register / guest gate. Shown on first visit.
 *
 * Three paths:
 *   1. Sign in with Google     (only if server has GOOGLE_CLIENT_ID configured)
 *   2. Username + password     (real account, stored in SQLite on the server)
 *   3. Continue as guest       (random per-browser session, lost on clear)
 *
 * On successful sign-in/register, the server sets a session cookie AND we
 * store the user id locally so the X-Session-Id header points to the same
 * folder/DB scope.
 */
import { useEffect, useState } from "react";
import { LogIn, User, Sparkles, UserPlus } from "lucide-react";

const STORAGE_NAME = "logicgate.user_name";
const STORAGE_SEEN = "logicgate.signin_seen";
const STORAGE_SID  = "logicgate.session_id";

export function getDisplayName(): string {
  try { return localStorage.getItem(STORAGE_NAME) || ""; } catch { return ""; }
}

export function signOut(): void {
  try {
    localStorage.removeItem(STORAGE_NAME);
    localStorage.removeItem(STORAGE_SID);
    localStorage.removeItem(STORAGE_SEEN);
  } catch {}
  fetch("/api/auth/logout", { method: "POST", credentials: "include" })
    .catch(() => {})
    .finally(() => window.location.reload());
}

type Mode = "choose" | "login" | "register";

export function SignInGate() {
  const [open, setOpen] = useState(() => {
    try { return !localStorage.getItem(STORAGE_SEEN); }
    catch { return true; }
  });
  const [mode, setMode]   = useState<Mode>("choose");
  const [username, setU]  = useState("");
  const [password, setP]  = useState("");
  const [busy, setBusy]   = useState(false);
  const [error, setError] = useState("");
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    fetch("/api/auth/config").then((r) => r.json())
      .then((d) => setGoogleEnabled(!!d.google_enabled)).catch(() => {});
    // If a session cookie is already valid, skip the gate.
    fetch("/api/auth/me", { credentials: "include" })
      .then((r) => r.json())
      .then((u) => {
        if (u.logged_in) {
          try {
            localStorage.setItem(STORAGE_NAME, u.name || "user");
            localStorage.setItem(STORAGE_SID,  u.id);
            localStorage.setItem(STORAGE_SEEN, "1");
          } catch {}
          setOpen(false);
        }
      }).catch(() => {});
  }, []);

  function close() {
    try { localStorage.setItem(STORAGE_SEEN, "1"); } catch {}
    setOpen(false);
  }

  function guest() {
    close();
  }

  async function submit() {
    setError("");
    setBusy(true);
    try {
      const path = mode === "register" ? "/api/auth/register" : "/api/auth/login";
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || `HTTP ${res.status}`);
        return;
      }
      const u = data.user;
      try {
        localStorage.setItem(STORAGE_NAME, u.name || username);
        localStorage.setItem(STORAGE_SID,  u.id);
        localStorage.setItem(STORAGE_SEEN, "1");
      } catch {}
      // Reload so X-Session-Id is set on all subsequent calls
      window.location.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[110] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-bg-800 border border-accent/30 rounded-xl shadow-2xl max-w-md w-full p-6 space-y-5">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-accent/15 border border-accent/40">
            <Sparkles size={20} className="text-accent" />
          </div>
          <h1 className="text-xl font-mono font-bold text-gray-100">LogicGate</h1>
          <p className="text-[11px] font-mono text-gray-500 leading-relaxed">
            Digital circuit designer with built-in ML.<br />
            Sign in to save your work across devices, or stay local as a guest.
          </p>
        </div>

        {mode === "choose" && (
          <div className="space-y-2.5">
            {googleEnabled && (
              <a href="/api/auth/google"
                 className="w-full flex items-center gap-3 px-4 py-3 rounded-lg bg-white hover:bg-gray-100 text-gray-900 border border-gray-300 transition-all no-underline">
                <GoogleIcon />
                <div className="flex-1 text-left">
                  <div className="text-xs font-mono font-bold">Sign in with Google</div>
                  <div className="text-[9px] font-mono text-gray-600">One-click · Google account</div>
                </div>
              </a>
            )}

            <button onClick={() => { setMode("login"); setError(""); }}
              className="w-full flex items-center gap-3 px-4 py-3 rounded-lg bg-accent hover:bg-accent-hover text-white border border-accent/60 transition-all">
              <LogIn size={14} />
              <div className="flex-1 text-left">
                <div className="text-xs font-mono font-bold">Sign in</div>
                <div className="text-[9px] font-mono opacity-80">Username + password · sync across devices</div>
              </div>
            </button>

            <button onClick={() => { setMode("register"); setError(""); }}
              className="w-full flex items-center gap-3 px-4 py-3 rounded-lg bg-bg-700 hover:bg-bg-600 text-gray-200 border border-bg-600 hover:border-accent/40 transition-all">
              <UserPlus size={14} />
              <div className="flex-1 text-left">
                <div className="text-xs font-mono font-bold">Create account</div>
                <div className="text-[9px] font-mono text-gray-500">Free · 30 seconds · circuits saved online</div>
              </div>
            </button>

            <button onClick={guest}
              className="w-full flex items-center gap-3 px-4 py-3 rounded-lg bg-bg-700/50 hover:bg-bg-700 text-gray-400 border border-bg-600/50 transition-all">
              <User size={14} />
              <div className="flex-1 text-left">
                <div className="text-xs font-mono font-bold">Continue as guest</div>
                <div className="text-[9px] font-mono text-gray-600">Saved to this browser only</div>
              </div>
            </button>
          </div>
        )}

        {(mode === "login" || mode === "register") && (
          <div className="space-y-3">
            <div className="text-[10px] font-mono text-gray-500 text-center">
              {mode === "register"
                ? "Pick a username (letters, digits, _ or -) and a password ≥ 6 chars."
                : "Welcome back."}
            </div>
            <div>
              <label className="text-[8px] font-mono uppercase tracking-widest text-gray-600 block mb-1">Username</label>
              <input autoFocus
                className="w-full bg-bg-700 border border-bg-600 rounded-lg px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-accent transition-colors"
                value={username} onChange={(e) => setU(e.target.value)}
                placeholder="ananya" maxLength={32} />
            </div>
            <div>
              <label className="text-[8px] font-mono uppercase tracking-widest text-gray-600 block mb-1">Password</label>
              <div className="relative">
                <input type={showPassword ? "text" : "password"}
                  className="w-full bg-bg-700 border border-bg-600 rounded-lg pl-3 pr-10 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-accent transition-colors"
                  value={password} onChange={(e) => setP(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submit()}
                  placeholder="at least 6 characters" />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-500 hover:text-accent transition-colors"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  title={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "🙈" : "👁"}
                </button>
              </div>
            </div>
            {error && <div className="text-[10px] font-mono text-err">{error}</div>}
            <div className="flex gap-2">
              <button onClick={() => setMode("choose")}
                className="px-4 py-2 rounded-lg bg-bg-700 hover:bg-bg-600 text-gray-400 text-xs font-mono border border-bg-600">
                Back
              </button>
              <button onClick={submit} disabled={busy || !username || password.length < 6}
                className="flex-1 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-mono font-bold disabled:opacity-40 transition-all">
                {busy ? "…" : (mode === "register" ? "Create account" : "Sign in")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 48 48">
      <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.5 29.3 4.5 24 4.5 13.2 4.5 4.5 13.2 4.5 24S13.2 43.5 24 43.5 43.5 34.8 43.5 24c0-1.3-.1-2.6-.4-3.9z"/>
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 16 19 13 24 13c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.5 29.3 4.5 24 4.5c-7.4 0-13.8 4.1-17.7 10.2z"/>
      <path fill="#4CAF50" d="M24 43.5c5.2 0 9.9-2 13.5-5.2l-6.2-5.2c-2 1.5-4.6 2.4-7.3 2.4-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.3 39.2 16 43.5 24 43.5z"/>
      <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.2 5.7l6.2 5.2c4.4-4.1 7.2-10.1 7.2-16.9 0-1.3-.1-2.6-.5-3.9z"/>
    </svg>
  );
}
