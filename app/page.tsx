const sections = [
  {
    title: "Math Foundations",
    description:
      "Core mathematical tools used across engineering, algorithms, signals, hardware, and numerical modeling.",
    courses: [
      "Multivariable Calculus",
      "Discrete Mathematics",
      "Probability and Statistics",
      "Numerical Computations",
    ],
  },
  {
    title: "Engineering Foundations",
    description:
      "Physics and device-level concepts that support circuits, semiconductors, and physical systems.",
    courses: [
      "Mechanics",
      "Electricity and Magnetism",
      "Quantum / Semiconductor Basics",
    ],
  },
  {
    title: "Programming and Software",
    description:
      "Software construction, low-level programming, memory, algorithms, and computational problem solving.",
    courses: [
      "Introduction to Systems Programming",
      "Data Structures and Algorithms",
    ],
  },
  {
    title: "Computer Systems",
    description:
      "Execution, memory, concurrency, architecture, operating systems, and applied system security.",
    courses: [
      "Operating Systems",
      "Intro to Computer Architecture",
      "System Security",
    ],
  },
  {
    title: "Hardware and Circuits",
    description:
      "Digital and electrical hardware concepts from circuit analysis through programmable logic and VLSI.",
    courses: [
      "Electrical Circuit Design",
      "FPGA Design",
      "Digital Integrated Circuits",
    ],
  },
  {
    title: "Signals and Networks",
    description:
      "Signal behavior, frequency-domain analysis, communication systems, and networked data transfer.",
    courses: [
      "Signals and Systems",
      "Communication Networks",
    ],
  },
  {
    title: "Engineering Communication",
    description:
      "Technical writing, documentation, reports, specifications, and engineering communication strategy.",
    courses: ["Technical Writing"],
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <section className="mx-auto max-w-6xl px-6 py-16">
        <p className="text-sm font-medium uppercase tracking-[0.3em] text-zinc-500">
          The Library of Vincandria
        </p>

        <h1 className="mt-6 max-w-4xl text-5xl font-semibold tracking-tight text-white md:text-7xl">
          A structured engineering knowledge base.
        </h1>

        <p className="mt-6 max-w-3xl text-lg leading-8 text-zinc-400">
          Organized course knowledge, equations, diagrams, systems concepts, and
          technical explanations from computer engineering, mathematics,
          hardware, software, physics, and communication.
        </p>

        <div className="mt-14 grid gap-6 md:grid-cols-2">
          {sections.map((section) => (
            <article
              key={section.title}
              className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 shadow-sm"
            >
              <h2 className="text-2xl font-semibold text-white">
                {section.title}
              </h2>

              <p className="mt-3 text-sm leading-6 text-zinc-400">
                {section.description}
              </p>

              <ul className="mt-6 space-y-2">
                {section.courses.map((course) => (
                  <li
                    key={course}
                    className="rounded-xl border border-zinc-800 bg-zinc-950 px-4 py-3 text-sm text-zinc-300"
                  >
                    {course}
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}