import Link from "next/link";

export default function NotFound() {
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">Not found</h1>
      <p className="dim text-sm">
        That page, scan or share link does not exist — or it belongs to another organisation, which
        we report the same way on purpose.
      </p>
      <Link href="/app">Back to your scans</Link>
    </div>
  );
}
