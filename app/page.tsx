/*
TODO
> Home Page <
  - Make it look better
  - Account for shrinking page size
  - Update sections and about

> Page 1 <
  - Make look pretty
  - Make admin stuff
  - I also want a bar on the side to go to different sections

*/

/*
background: zinc-950
dark foreground: #202021
small foregrounds: #202021aa
light foreground/headings: #d2d2d2
text: #d2d2d2cc
mini borders: #d2d2d222
mini border active: 
borders: zinc-700

*/
import TopNav from "./components/TopNav";

// Topics
const sections = [
  {
    title: "Math Foundations",
    href: "/math-foundations",
    iconName: "math",
    description:
      "Better description later",
  },
  {
    title: "Engineering Foundations",
    href: "/engineering-foundations",
    iconName: "engineering",
    description:
      "Better description later",
  },
  {
    title: "Programming and Software",
    href: "/programming-and-software",
    iconName: "programming",
    description:
      "Better description later",
  },
  {
    title: "Computer Systems",
    href: "/computer-systems",
    iconName: "computer",
    description:
      "Better description later",
  },
  {
    title: "Hardware and Circuits",
    href: "/hardware-and-circuits",
    iconName: "circuits",
    description:
      "Better description later",
  },
  {
    title: "Signals and Networks",
    href: "/signals-and-networks",
    iconName: "signals",
    description:
      "Better description later",
  },
  {
    title: "Engineering Communication",
    href: "/engineering-communication",
    iconName: "writing",
    description:
      "Better description later",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-zinc-950 text-[#d2d2d2]">
      {/* Top navigation */}
      <TopNav />

      <section className="mx-auto max-w-6xl px-2 py-10">
        {/* Title */}
        <p className="text-sm font-medium uppercase tracking-[0.35em] text-[#d2d2d285]">
          The Library of Vincandria
        </p>

        {/* Header and description */}
        <h1 className="mt-6 text-5xl font-semibold tracking-tight text-white md:text-7xl">
          A structured engineering memory bank.
        </h1>

        <p className="mt-6 max-w-3xl text-lg leading-8 text-[#d2d2d2cc]">
          Organized course knowledge... add better abstract when done
        </p>

        {/* Scaffold of topics */}
        <div className="mt-14 space-y-6 pb-8">
          {sections.map((section) => (
            <details
              key={section.title}
              className="group rounded-2xl border border-zinc-700 bg-[#202021aa] p-8 transition hover:border-[#d2d2d2] open:border-[#d2d2d2]"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
                <h2 className="text-2xl font-semibold text-[#d2d2d2]">
                  {section.title}
                </h2>
              <span className="text-2xl text-[#d2d2d2] transition-transform group-hover:text-white group-open:rotate-45 group-open:text-white">
                +
              </span>
              </summary>
              <div className="mt-5 border-t border-[#d2d2d222] pt-4">
                <p className="text-lg leading-10 text-[#d2d2d2cc]">
                  {section.description}
                </p>
                <a
                  href={section.href}
                  aria-label={`Open ${section.title}`}
                  className="mt-4 flex justify-end text-6xl text-[#d2d2d2] pe-4 transition hover:translate-x-2 hover:text-white"
                >
                  →
                </a>
              </div>
            </details>
          ))}
        </div>
      </section>
      {/* Footer */}
      <footer className="border-t border-zinc-700 py-8">
        <div className="mx-auto flex max-w-6xl items-center justify-center gap-12">
          <a
            href="https://www.linkedin.com/in/vincematolka/"
            target="_blank"
            rel="noopener noreferrer"
            className="group flex items-center gap-2 text-sm text-[#d2d2d2aa] transition hover:text-white"
          >
            <img
              src="/linkedin-icon-light.png"
              alt="LinkedIn"
              className="h-6 w-6 object-contain opacity-80 transition group-hover:opacity-100"
            />
            <span>LinkedIn</span>
          </a>

          <a
            href="https://github.com/matolks"
            target="_blank"
            rel="noopener noreferrer"
            className="group flex items-center gap-2 text-sm text-[#d2d2d2aa] transition hover:text-white"
          >
            <img
              src="/github-icon-light.png"
              alt="GitHub"
              className="h-6 w-6 object-contain opacity-80 transition group-hover:opacity-100"
            />
            <span>GitHub</span>
          </a>
        </div>
      </footer>
    </main>
  );
}