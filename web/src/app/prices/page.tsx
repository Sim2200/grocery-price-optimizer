"use client";

import dynamic from "next/dynamic";
import { useApp } from "../AppContext";

// The charts library is large, so this page's code is loaded only when opened.
const PricesPage = dynamic(() => import("../../views/PricesPage"), {
  ssr: false,
  loading: () => <p className="muted">Loading...</p>,
});

export default function Prices() {
  const { dataVersion, refresh } = useApp();
  return <PricesPage version={dataVersion} onWatchlistChanged={refresh} />;
}
