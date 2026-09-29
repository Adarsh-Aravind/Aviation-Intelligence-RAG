"use client";

import { Lock } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { LogoMark } from "@/components/logo";
import { useSession } from "@/components/session-provider";
import { Button, Card, Input } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.login(password);
      await refresh();
      toast.success("Signed in as admin");
      router.push("/documents");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center px-4 py-10">
      <Card className="w-full max-w-sm p-6">
        <LogoMark className="h-10 w-10" />
        <h1 className="mt-4 text-lg font-semibold">Admin sign-in</h1>
        <p className="mt-1 text-sm text-muted">Required to upload or delete documents. Asking questions is open to everyone.</p>
        <form onSubmit={submit} className="mt-6 space-y-3">
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" />
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Admin password"
              autoComplete="current-password"
              className="pl-9"
              autoFocus
            />
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
          <Button type="submit" className="w-full" loading={loading} disabled={!password}>
            Sign in
          </Button>
        </form>
      </Card>
    </div>
  );
}
