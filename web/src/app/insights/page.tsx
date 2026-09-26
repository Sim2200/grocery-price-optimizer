"use client";

import dynamic from "next/dynamic";
import { useApp } from "../AppContext";

// Charts here too, so the page is loaded on demand.
const InsightsPage = dynamic(() => import("../../views/InsightsPage"), {
  ssr: false,
  loading: () => <p className="muted">Loading...</p>,
});

export default function Insights() {
  const { dataVersion } = useApp();
  return <InsightsPage version={dataVersion} />;
}
