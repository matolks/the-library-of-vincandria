"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";

const sections = [
  { label: "Math",        href: "/math-foundations",          light: "/math-icon-light.png",        dark: "/math-icon-dark.png"        },
  { label: "Engineering", href: "/engineering-foundations",   light: "/engineering-icon-light.png", dark: "/engineering-icon-dark.png" },
  { label: "Programming", href: "/programming-and-software",  light: "/programming-icon-light.png", dark: "/programming-icon-dark.png" },
  { label: "Systems",     href: "/computer-systems",          light: "/computer-icon-light.png",    dark: "/computer-icon-dark.png"    },
  { label: "Circuits",    href: "/hardware-and-circuits",     light: "/circuits-icon-light.png",    dark: "/circuits-icon-dark.png"    },
  { label: "Signals",     href: "/signals-and-networks",      light: "/signals-icon-light.png",     dark: "/signals-icon-dark.png"     },
  { label: "Writing",     href: "/engineering-communication", light: "/writing-icon-light.png",     dark: "/writing-icon-dark.png"     },
];

export default function TopNav() {
  const pathname = usePathname();

  return (
    <header>
      {/* Main nav bar */}
      <nav className="sticky top-0 z-10 flex items-center justify-between border-b border-[#ffffff0f] bg-[#0e0e0fcc] px-10 py-4 backdrop-blur-md">
        <span className="font-mono text-[11px] font-light tracking-[0.2em] uppercase text-[#d2d2d244]">
          Vincandria / Library
        </span>
        <div className="flex items-center gap-6">
          <Link href="/" className="font-mono text-[12px] font-light tracking-widest uppercase text-[#d2d2d244] transition-colors hover:text-[#d2d2d2]">
            Browse
          </Link>
          <Link href="/search" className="font-mono text-[12px] font-light tracking-widest uppercase text-[#d2d2d244] transition-colors hover:text-[#d2d2d2]">
            Search
          </Link>
          <Link
            href="/admin"
            className="rounded-sm border border-[#d2d2d218] px-2.5 py-1 font-mono text-[12px] font-light tracking-widest uppercase text-[#d2d2d244] transition-colors hover:border-[#d2d2d244] hover:text-[#d2d2d2]"
          >
            Admin
          </Link>
        </div>
      </nav>

      {/* Icon strip */}
      <div className="flex overflow-x-auto border-b border-[#ffffff0f]" style={{ scrollbarWidth: "none" }}>
        {sections.map((s) => {
          const active = pathname === s.href || pathname.startsWith(s.href + "/");
          return (
            <Link
              key={s.href}
              href={s.href}
              className={`group flex flex-1 flex-col items-center justify-center gap-2 border-r border-[#ffffff0f] px-4 py-5 last:border-r-0 transition-colors no-underline ${
                active ? "bg-[#d2d2d2]" : "hover:bg-[#d2d2d2]"
              }`}
            >
              {/* Light icon — shown by default, hidden on hover/active */}
              <div className={active ? "hidden" : "block group-hover:hidden"}>
                <Image src={s.light} alt={s.label} width={32} height={32} className="object-contain" />
              </div>
              {/* Dark icon — shown on hover/active */}
              <div className={active ? "block" : "hidden group-hover:block"}>
                <Image src={s.dark} alt={s.label} width={32} height={32} className="object-contain" />
              </div>
              <span
                className={`font-mono text-[9px] font-light tracking-[0.12em] uppercase text-center leading-tight transition-colors ${
                  active ? "text-[#20202188]" : "text-[#d2d2d244] group-hover:text-[#20202188]"
                }`}
              >
                {s.label}
              </span>
            </Link>
          );
        })}
      </div>
    </header>
  );
}