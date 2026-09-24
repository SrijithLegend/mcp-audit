"use client";

import { Alert, Button } from "@/components/ui";

export default function ErrorBoundary({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="space-y-3">
      <Alert kind="error" action={<Button onClick={reset}>Try again</Button>}>
        Something broke in this page. The details are in our error tracker, with request bodies and
        credentials scrubbed.
      </Alert>
    </div>
  );
}
