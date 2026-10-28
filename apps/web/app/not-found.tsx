import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main" className="center-page stack">
      <h1>Page not found</h1>
      <p>This address does not match any screen in the NGSIRS console.</p>
      <p>
        <Link href="/dashboard">Go to the Compliance Overview</Link>
      </p>
    </main>
  );
}
