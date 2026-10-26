import { useState } from "react";
import Logo from "./Logo";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function Login({ onLogin }) {
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    const endpoint = mode === "login" ? "/auth/login" : "/auth/signup";

    try {
      const res = await fetch(`${API}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json().catch(() => null);

      if (!res.ok) {
        const msg =
          data?.detail ||
          (mode === "login"
            ? "Incorrect email or password."
            : "Could not create account.");
        setError(msg);
        return;
      }

      onLogin(data);
    } catch {
      setError("Could not reach the server. Is the backend running?");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-ink-50 via-brand-50 to-ink-50 px-4">
      <div className="w-full max-w-sm">
        <div className="flex justify-center mb-8">
          <Logo size={44} />
        </div>

        <div className="bg-white border border-ink-100 rounded-2xl shadow-xl shadow-brand-900/5 p-8">
          <h1 className="text-xl font-semibold text-ink-900 mb-1">
            {mode === "login" ? "Sign in" : "Create account"}
          </h1>
          <p className="text-sm text-ink-400 mb-6">
            Access the VeriLex compliance research assistant.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-ink-600 mb-1.5">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-lg border border-ink-200 px-3.5 py-2.5 text-sm text-ink-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100 transition"
                placeholder="you@example.com"
                autoFocus
                required
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-600 mb-1.5">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-ink-200 px-3.5 py-2.5 text-sm text-ink-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100 transition"
                placeholder="••••••••"
                required
                minLength={8}
              />
            </div>

            {error && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-brand-500 hover:bg-brand-600 disabled:bg-ink-200 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg py-2.5 transition shadow-sm shadow-brand-500/30"
            >
              {submitting
                ? "Please wait…"
                : mode === "login"
                ? "Sign in"
                : "Create account"}
            </button>
          </form>

          <div className="text-center mt-5">
            {mode === "login" ? (
              <p className="text-sm text-ink-400">
                Don&rsquo;t have an account?{" "}
                <button
                  type="button"
                  onClick={() => { setMode("signup"); setError(""); }}
                  className="text-brand-500 hover:text-brand-600 font-medium transition cursor-pointer"
                >
                  Sign up
                </button>
              </p>
            ) : (
              <p className="text-sm text-ink-400">
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => { setMode("login"); setError(""); }}
                  className="text-brand-500 hover:text-brand-600 font-medium transition cursor-pointer"
                >
                  Sign in
                </button>
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
