import TopNav from "../components/TopNav";

export default function EngineeringCommunicationPage() {
  return (
    <main className="min-h-screen bg-zinc-950 text-[#d2d2d2]">
      <TopNav />

      <section className="mx-auto max-w-6xl px-2 py-10">
        <a href="/" className="text-sm text-zinc-400 hover:text-white">
          ← Back to Home
        </a>

        <h1 className="mt-6 text-5xl font-semibold tracking-tight text-white md:text-7xl">
          Engineering Communication
        </h1>

        <p className="mt-6 max-w-3xl text-lg leading-8 text-[#d2d2d2cc]">
          Update
        </p>
      </section>
    </main>
  );
}