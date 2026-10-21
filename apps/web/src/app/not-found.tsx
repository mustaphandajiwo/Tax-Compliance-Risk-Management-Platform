import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main" className="login-wrap">
      <div className="card card-pad" style={{ maxWidth: 480 }}>
        <h1>Page not found</h1>
        <p className="muted">The page you requested does not exist.</p>
        <Link className="btn btn-primary" href="/">
          Go to overview
        </Link>
      </div>
    </main>
  );
}
