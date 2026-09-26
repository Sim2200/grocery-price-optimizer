"use client";

import ReceiptsPage from "../../views/ReceiptsPage";
import { useApp } from "../AppContext";

export default function Receipts() {
  const { dataVersion, refresh } = useApp();
  return <ReceiptsPage version={dataVersion} onChanged={refresh} />;
}
