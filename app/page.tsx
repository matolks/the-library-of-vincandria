export default function Home() {
  return (
    <main className="min-h-screen bg-black text-white px-8 py-12">
      <section className="max-w-5xl mx-auto">
        <p className="text-sm uppercase tracking-widest text-zinc-400">
          The Library of Vincandria
        </p>

        <h1 className="mt-6 text-5xl font-bold tracking-tight">
          A personal engineering knowledge base.
        </h1>

        <p className="mt-6 max-w-2xl text-lg text-zinc-300">
          Organized notes, equations, diagrams, and project explanations from
          computer engineering, mathematics, systems, hardware, and technical
          communication.
        </p>

        <div className="mt-12 grid gap-6 md:grid-cols-3">
          <div className="rounded-2xl border border-zinc-800 p-6">
            <h2 className="text-xl font-semibold">Math Foundations</h2>
            <p className="mt-3 text-zinc-400">
              Calculus, discrete math, probability, numerical computation, and
              signal analysis.
            </p>
          </div>

          <div className="rounded-2xl border border-zinc-800 p-6">
            <h2 className="text-xl font-semibold">Engineering Systems</h2>
            <p className="mt-3 text-zinc-400">
              Operating systems, computer architecture, networking, FPGA design,
              and VLSI.
            </p>
          </div>

          <div className="rounded-2xl border border-zinc-800 p-6">
            <h2 className="text-xl font-semibold">Projects</h2>
            <p className="mt-3 text-zinc-400">
              Applied work involving software, cybersecurity, reverse proxies,
              embedded systems, and technical design.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}