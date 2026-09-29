"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api } from "@/lib/api";

interface SessionState {
  admin: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionState>({
  admin: false,
  loading: true,
  refresh: async () => {},
  logout: async () => {},
});

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [admin, setAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setAdmin((await api.session()).admin);
    } catch {
      setAdmin(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setAdmin(false);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial session fetch
    void refresh();
  }, [refresh]);

  return (
    <SessionContext.Provider value={{ admin, loading, refresh, logout }}>{children}</SessionContext.Provider>
  );
}

export const useSession = () => useContext(SessionContext);
