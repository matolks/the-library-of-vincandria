import Link from "next/link";
import TopNav from "./components/TopNav";

const sections = [
  {
    index: "01",
    title: "Math Foundations",
    href: "/math-foundations",
    tags: ["Multivariable Calculus", "Discrete Math", "Probability", "Numerical Methods"],
  },
  {
    index: "02",
    title: "Engineering Foundations",
    href: "/engineering-foundations",
    tags: ["Mechanics", "E&M", "Quantum / Semiconductor"],
  },
  {
    index: "03",
    title: "Programming and Software",
    href: "/programming-and-software",
    tags: ["Systems Programming", "Data Structures & Algorithms"],
  },
  {
    index: "04",
    title: "Computer Systems",
    href: "/computer-systems",
    tags: ["Operating Systems", "Architecture", "Security", "Networking"],
  },
  {
    index: "05",
    title: "Hardware and Circuits",
    href: "/hardware-and-circuits",
    tags: ["Circuit Design", "FPGA", "Digital ICs"],
  },
  {
    index: "06",
    title: "Signals and Networks",
    href: "/signals-and-networks",
    tags: ["Signals & Systems", "Communication Networks"],
  },
  {
    index: "07",
    title: "Engineering Communication",
    href: "/engineering-communication",
    tags: ["Technical Writing", "Documentation", "Capstone Reports"],
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-[#0e0e0f] text-[#d2d2d2]">
      <TopNav />

      <section className="mx-auto max-w-[1100px] px-10 py-20">
        {/* Eyebrow */}
        <p className="font-mono text-[10px] font-light tracking-[0.4em] uppercase text-[#d2d2d244] mb-8">
          The Library of Vincandria
        </p>

        {/* Headline */}
        <h1 className="font-serif text-[clamp(2.8rem,6vw,5.5rem)] font-medium leading-[1.08] tracking-tight text-[#efefef] max-w-[880px] mb-20">
          A structured{" "}
          <em className="italic text-[#d2d2d299]">engineering</em>
          <br />
          and fundamentals
          <br />
          memory bank.
        </h1>

        {/* Divider */}
        <div className="w-12 h-px bg-[#d2d2d222] mb-12" />

        {/* Section list */}
        <div className="border border-[#ffffff0d] rounded-[4px] overflow-hidden">
          {sections.map((s) => (
            <Link
              key={s.href}
              href={s.href}
              className="group grid grid-cols-[1fr_auto] items-center gap-4 bg-[#0e0e0f] px-8 py-7 transition-colors hover:bg-[#161617] border-b border-[#ffffff0d] last:border-b-0 no-underline"
            >
              <div className="flex items-baseline gap-6">
                <span className="font-mono text-[11px] font-light text-[#d2d2d222] min-w-[24px]">
                  {s.index}
                </span>
                <div>
                  <p className="font-serif text-[1.35rem] font-medium text-[#d2d2d2cc] mb-1.5 transition-colors group-hover:text-[#efefef]">
                    {s.title}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {s.tags.map((tag) => (
                      <span
                        key={tag}
                        className="font-mono text-[10px] font-light tracking-[0.06em] text-[#d2d2d233] border border-[#d2d2d211] rounded-[2px] px-1.5 py-0.5"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
              <span className="text-lg text-[#d2d2d255] opacity-0 -translate-x-1.5 transition-all group-hover:opacity-100 group-hover:translate-x-0">
                →
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-[#ffffff0d] py-10">
        <div className="mx-auto flex max-w-[1100px] items-center justify-between px-10">
          <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-[#d2d2d222]">
            © 2026 Vince Matolka
          </span>
          <div className="flex items-center gap-8">
            <a
              href="https://www.linkedin.com/in/vincematolka/"
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-center gap-1.5 font-mono text-[12px] font-light tracking-[0.08em] text-[#d2d2d244] transition-colors hover:text-[#d2d2d2] no-underline"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/linkedin-icon-light.png" alt="" className="h-4 w-4 object-contain opacity-50 transition group-hover:opacity-100" />
              LinkedIn
            </a>
            <a
              href="https://github.com/matolks"
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-center gap-1.5 font-mono text-[12px] font-light tracking-[0.08em] text-[#d2d2d244] transition-colors hover:text-[#d2d2d2] no-underline"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/github-icon-light.png" alt="" className="h-4 w-4 object-contain opacity-50 transition group-hover:opacity-100" />
              GitHub
            </a>
          </div>
        </div>
      </footer>
    </main>
  );
}