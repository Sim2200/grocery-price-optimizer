"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// The root URL has no content of its own; the first tab is the home page.
// (A client-side redirect, because the build is a static export.)
export default function Home() {
  const router = useRouter();
  useEffect(() => {
    if (!window.location.hash) router.replace("/upload");
  }, [router]);
  return null;
}
