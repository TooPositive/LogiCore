"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Search,
  ShieldCheck,
  BarChart3,
  Activity,
  Receipt,
} from "lucide-react";
import { useEffect, useState } from "react";
import { health } from "@/lib/api";

const links = [
  { href: "/", label: "Fleet Dashboard", icon: LayoutDashboard },
  { href: "/search", label: "Corporate Brain", icon: Search },
  { href: "/audit", label: "Freight Audit", icon: Receipt },
  { href: "/compliance", label: "Compliance", icon: ShieldCheck },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

export function SidebarNav() {
  const pathname = usePathname();
  const [apiUp, setApiUp] = useState<boolean | null>(null);

  useEffect(() => {
    const check = async () => {
      const res = await health.check();
      setApiUp(res !== null);
    };
    check();
    const t = setInterval(check, 10000);
    return () => clearInterval(t);
  }, []);

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-56 flex-col border-r border-zinc-800 bg-zinc-950">
      {/* Logo */}
      <div className="flex h-14 items-center px-5">
        <Link href="/" className="text-lg font-bold tracking-tight">
          Logi<span className="text-emerald-400">Core</span>
        </Link>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {links.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                active
                  ? "border-l-2 border-emerald-400 bg-emerald-500/10 text-emerald-400"
                  : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Status footer */}
      <div className="border-t border-zinc-800 px-5 py-3">
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Activity className="h-3 w-3" />
          <span>API</span>
          <span
            className={`ml-auto h-2 w-2 rounded-full ${
              apiUp === null
                ? "bg-zinc-600"
                : apiUp
                  ? "bg-emerald-400"
                  : "bg-red-400"
            }`}
          />
          <span className={apiUp ? "text-emerald-400" : "text-zinc-500"}>
            {apiUp === null ? "..." : apiUp ? "Online" : "Offline"}
          </span>
        </div>
      </div>
    </aside>
  );
}
