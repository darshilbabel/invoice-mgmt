import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, setToken, setUnauthorizedHandler, getToken } from "../api/client";
import type { LoginResponse, User } from "../types";

interface AuthState {
  user: User | null;
  /** True until the stored token has been checked against /api/auth/me/. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // A stored token proves nothing — it may have been revoked by a logout
  // elsewhere. Confirm it against the API before treating the user as signed in.
  useEffect(() => {
    let cancelled = false;
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .get<User>("/auth/me/")
      .then((me) => !cancelled && setUser(me))
      .catch(() => !cancelled && setUser(null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => setUnauthorizedHandler(() => setUser(null)), []);

  const login = useCallback(async (email: string, password: string) => {
    const { token, user: me } = await api.post<LoginResponse>("/auth/login/", {
      email,
      password,
    });
    setToken(token);
    setUser(me);
  }, []);

  const logout = useCallback(async () => {
    // Logout is a real server-side revocation, but the local session must end
    // even if that call fails.
    try {
      await api.post("/auth/logout/");
    } finally {
      setToken(null);
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside an AuthProvider");
  return context;
}
