"use client";

import { usePathname } from "next/navigation";

const sections = [
  { title: "Math Foundations",        href: "/math-foundations",          iconName: "math"        },
  { title: "Engineering Foundations", href: "/engineering-foundations",   iconName: "engineering" },
  { title: "Programming and Software",href: "/programming-software",  iconName: "programming" },
  { title: "Computer Systems",        href: "/computer-systems",          iconName: "computer"    },
  { title: "Hardware and Circuits",   href: "/hardware-circuits",     iconName: "circuits"    },
  { title: "Signals and Networks",    href: "/signals-networks",      iconName: "signals"     },
  { title: "Engineering Communication",href: "/engineering-communication",iconName: "writing"     },
];

export default function TopNav() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-zinc-700 bg-zinc-950">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7">
        {sections.map((section) => {
          const isActive = pathname === section.href || pathname.startsWith(section.href + "/");
          return (
            <a
              key={section.title}
              href={section.href}
              aria-label={section.title}
              className={`group flex min-h-32 flex-col items-center justify-center gap-3 border-b border-r border-zinc-700 px-4 py-4 text-center transition sm:min-h-28 ${
                isActive ? "bg-[#d2d2d2]" : "bg-zinc-950 hover:bg-[#d2d2d2]"
              }`}
            >
              <div className="relative h-14 w-14">
                <img
                  src={`/${section.iconName}-icon-light.png`}
                  alt=""
                  className={`absolute inset-0 h-full w-full object-contain transition ${
                    isActive ? "opacity-0" : "opacity-100 group-hover:opacity-0"
                  }`}
                />
                <img
                  src={`/${section.iconName}-icon-dark.png`}
                  alt=""
                  className={`absolute inset-0 h-full w-full object-contain transition ${
                    isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                  }`}
                />
              </div>
            </a>
          );
        })}
      </div>
    </nav>
  );
}