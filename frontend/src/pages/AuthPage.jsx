import { useState } from "react";
import {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  signInWithPopup,
  sendPasswordResetEmail,
} from "firebase/auth";
import { Bot, Lock, Mail } from "lucide-react";
import { auth, isFirebaseConfigured } from "../firebase";

export default function AuthScreen() {
  const [isSignup, setIsSignup] = useState(false);
  const [isResetMode, setIsResetMode] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setMessage("");
    if (!isFirebaseConfigured || !auth) {
      setError(
        "Firebase authentication is not configured. Add your Firebase settings to frontend/.env."
      );
      return;
    }
    setLoading(true);
    try {
      if (isResetMode) {
        await sendPasswordResetEmail(auth, email);
        setMessage("Password reset email sent. Check your inbox.");
      } else if (isSignup) {
        await createUserWithEmailAndPassword(auth, email, password);
      } else {
        await signInWithEmailAndPassword(auth, email, password);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    setError("");
    if (!isFirebaseConfigured || !auth) {
      setError("Firebase authentication is not configured. Add your Firebase settings to frontend/.env.");
      return;
    }
    setLoading(true);
    try {
      await signInWithPopup(auth, new GoogleAuthProvider());
    } catch (err) {
      setError(err.code === "auth/operation-not-allowed"
        ? "Google sign-in is not enabled for this Firebase project. Enable it in Firebase Authentication settings."
        : err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#08080c] flex items-center justify-center p-4 relative overflow-hidden">
      {/* Subtle ambient violet glow */}
      <div className="absolute w-[500px] h-[500px] rounded-full bg-violet-600/10 blur-[140px] pointer-events-none" />

      <div className="w-full max-w-md bg-white/[0.03] backdrop-blur-2xl rounded-2xl p-8 border border-white/[0.08] shadow-2xl relative z-10">
        <div className="flex items-center gap-3 mb-7">
          <div className="p-3 rounded-xl bg-violet-500/15 border border-violet-500/30 text-violet-400">
            <Bot className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-zinc-100 tracking-tight">
              AURA · Browser Agent
            </h1>
          </div>
        </div>

        {!isResetMode && <button
          type="button"
          onClick={handleGoogleSignIn}
          disabled={loading}
          className="w-full py-2.5 px-3 rounded-xl bg-white text-zinc-800 hover:bg-zinc-100 font-medium text-sm flex items-center justify-center gap-3 transition cursor-pointer disabled:opacity-50"
        >
          <svg aria-hidden="true" viewBox="0 0 48 48" className="h-5 w-5">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5Z" transform="translate(0 4)" />
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.76 7.18l7.73 6C44.42 38.05 47 31.95 47 24.55Z" />
            <path fill="#FBBC05" d="M10.53 28.59a14.4 14.4 0 0 1 0-9.18l-7.98-6.19a23.9 23.9 0 0 0 0 21.56l7.98-6.19Z" transform="translate(0 4)" />
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.91-5.8l-7.73-6c-2.14 1.44-4.89 2.3-8.18 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48Z" transform="translate(0 -4)" />
          </svg>
          Continue with Google
        </button>}

        {!isResetMode && <div className="my-5 flex items-center gap-3 text-[10px] uppercase tracking-wider text-zinc-600">
          <span className="h-px flex-1 bg-white/[0.08]" />
          <span>or use email</span>
          <span className="h-px flex-1 bg-white/[0.08]" />
        </div>}

        <form onSubmit={handleSubmit} className="space-y-4">
          {!isResetMode && <div>
            <label className="block text-xs font-medium text-zinc-400 mb-1.5">
              Email Address
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="tejasvi@example.com"
                className="w-full pl-10 pr-3 py-2.5 bg-black/40 border border-white/10 rounded-xl text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-violet-500/60"
              />
            </div>
          </div>}

          <div>
            {!isResetMode && <>
              <div className="mb-1.5 flex items-center justify-between">
                <label className="block text-xs font-medium text-zinc-400">Password</label>
                {!isSignup && <button
                  type="button"
                  onClick={() => { setIsResetMode(true); setError(""); setMessage(""); }}
                  className="text-[11px] text-violet-400 hover:text-violet-300 cursor-pointer"
                >Forgot password?</button>}
              </div>
              <div className="relative">
                <Lock className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3" />
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-10 pr-3 py-2.5 bg-black/40 border border-white/10 rounded-xl text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-violet-500/60"
                />
              </div>
            </>}
          </div>

          {error && (
            <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300">
              {error}
            </div>
          )}
          {message && <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300">{message}</div>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-medium text-sm transition cursor-pointer disabled:opacity-50"
          >
            {loading
              ? isResetMode ? "Sending email..." : "Authenticating..."
              : isResetMode
              ? "Send Password Reset Email"
              : isSignup
              ? "Create Account"
              : "Sign In"}
          </button>
        </form>

        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={() => {
              setIsResetMode(false);
              setIsSignup(!isSignup);
              setError("");
              setMessage("");
            }}
            className="text-xs text-violet-400 hover:text-violet-300 cursor-pointer"
          >
            {isResetMode
              ? "Back to sign in"
              : isSignup
              ? "Already have an account? Sign in"
              : "Need an account? Sign up"}
          </button>
        </div>

      </div>
    </div>
  );
}
