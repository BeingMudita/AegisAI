import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, setToken, setUnauthorizedHandler } from "./api";
import type { User } from "./types";

const STORAGE_KEY = "aegisai.token";

function readStored(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(value: string | null): void {
  try {
    if (value) sessionStorage.setItem(STORAGE_KEY, value);
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable — the session just won't survive a reload */
  }
}

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    setToken(null);
    writeStored(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    const stored = readStored();
    if (!stored) {
      setReady(true);
      return;
    }
    setToken(stored);
    api
      .get<User>("/api/auth/me")
      .then(setUser)
      .catch(logout)
      .finally(() => setReady(true));
  }, [logout]);

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await api.login(username, password);
    setToken(access_token);
    writeStored(access_token);
    setUser(await api.get<User>("/api/auth/me"));
  }, []);

  return <AuthContext.Provider value={{ user, ready, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function isStaff(user: User | null): boolean {
  return user?.role === "ADMIN" || user?.role === "SECURITY_ANALYST";
}
