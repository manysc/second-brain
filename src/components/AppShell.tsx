import Link from "next/link";
import type { ReactNode } from "react";

const links = [
  ["Command center", "/dashboard"], ["Briefing", "/briefing"], ["Meetings", "/meetings"], ["Topics", "/topics"],
  ["Ideas", "/items?type=IDEA"], ["Decisions", "/decisions"], ["Actions", "/actions"], ["Questions", "/questions"],
  ["Review center", "/review"], ["Growth", "/growth"], ["Ask my brain", "/ask"],
];
export function AppShell({ children }: { children: ReactNode }) {
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><span className="brand-mark">SB</span><div><strong>Second Brain</strong><small>Work intelligence</small></div></div><nav>{links.map(([label, href]) => <Link key={href} href={href}>{label}</Link>)}</nav><div className="sidebar-foot"><span className="live-dot" /> Local knowledge base<br /><small>Evidence stays attached</small></div></aside><main className="main-content"><header className="topbar"><div className="crumb">WORKSPACE / KNOWLEDGE</div><Link className="search" href="/ask">Search your brain <kbd>⌘ K</kbd></Link></header>{children}</main></div>;
}
