"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search, Users, BarChart3, Leaf, Upload } from "lucide-react";

const navItems = [
  { href: "/", label: "Query", icon: Search },
  { href: "/ingest", label: "Ingest", icon: Upload },
  { href: "/peers", label: "Peers", icon: Users },
  { href: "/metrics", label: "Metrics", icon: BarChart3 },
];

export function Navigation() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-slate-700 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-50">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-aura-primary to-aura-secondary flex items-center justify-center">
              <span className="text-white font-bold text-lg">A</span>
            </div>
            <div>
              <h1 className="font-bold text-lg text-white">AURA</h1>
              <p className="text-xs text-slate-400">Federated RAG</p>
            </div>
          </Link>

          {/* Nav Links */}
          <div className="flex items-center gap-1">
            {navItems.map(({ href, label, icon: Icon }) => {
              const isActive = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  className={`
                    flex items-center gap-2 px-4 py-2 rounded-lg transition-colors
                    ${isActive
                      ? "bg-aura-primary/20 text-aura-accent"
                      : "text-slate-400 hover:text-white hover:bg-slate-800"
                    }
                  `}
                >
                  <Icon size={18} />
                  <span className="hidden sm:inline">{label}</span>
                </Link>
              );
            })}
          </div>

          {/* Carbon indicator */}
          <div className="flex items-center gap-2 text-sm">
            <Leaf size={16} className="text-green-400" />
            <span className="text-slate-400 hidden sm:inline">GreenOps</span>
          </div>
        </div>
      </div>
    </nav>
  );
}
