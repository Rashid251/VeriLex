import { useState, useEffect } from "react";
import Login from "./components/Login";
import Dashboard from "./components/Dashboard";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
  // null = loading, false = unauthenticated, object = user
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // On mount, call /auth/me to check if already logged in via cookie
  useEffect(() => {
    fetch(`${API}/auth/me`, { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setUser(data || false))
      .catch(() => setUser(false))
      .finally(() => setLoading(false));
  }, []);

  async function handleLogin(userData) {
    setUser(userData);
  }

  async function handleLogout() {
    await fetch(`${API}/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    setUser(false);
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-ink-50">
        <span className="text-sm text-ink-400">Loading…</span>
      </div>
    );
  }

  return user ? (
    <Dashboard user={user} onLogout={handleLogout} />
  ) : (
    <Login onLogin={handleLogin} />
  );
}
