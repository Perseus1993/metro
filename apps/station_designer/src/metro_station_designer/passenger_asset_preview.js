import React, { useEffect, useMemo, useRef, useState } from "react";

import {
  ASSET_PREVIEW_DEFS,
  mountPassengerAssetScene,
} from "./passenger_asset_scene.js?v=ops-config-1";

const h = React.createElement;

export function PassengerAssetPreview({ stats }) {
  const viewportRef = useRef(null);
  const [status, setStatus] = useState("loading");
  const previewItems = useMemo(() => assetPreviewItems(stats), [stats]);

  useEffect(() => {
    let disposeScene = () => {};
    let cancelled = false;
    const viewport = viewportRef.current;
    const onSceneStatus = (event) => {
      setStatus(event.detail?.status === "ready" ? "ready" : "failed");
    };
    viewport?.addEventListener("passenger-asset-scene-status", onSceneStatus);
    import("three")
      .then((THREE) => {
        if (cancelled || !viewportRef.current) return;
        disposeScene = mountPassengerAssetScene(THREE, viewportRef.current);
      })
      .catch(() => setStatus("failed"));
    return () => {
      cancelled = true;
      viewport?.removeEventListener("passenger-asset-scene-status", onSceneStatus);
      disposeScene();
    };
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.dataset.entryShare = String(previewItems[0]?.share || 0);
    viewport.dataset.exitShare = String(previewItems[1]?.share || 0);
  }, [previewItems]);

  return h("div", { className: "passenger-asset-preview" }, [
    h("div", { key: "viewport", className: "passenger-asset-preview__viewport", ref: viewportRef }, [
      status === "failed"
        ? h("div", { key: "fallback", className: "passenger-asset-preview__fallback" }, "3D 预览不可用")
        : null,
    ]),
    h(
      "div",
      { key: "legend", className: "passenger-asset-preview__legend" },
      previewItems.map((item) =>
        h("div", { key: item.id, className: "passenger-asset-preview__legend-item" }, [
          h("i", { key: "swatch", style: { background: item.color } }),
          h("span", { key: "label" }, item.label),
          h("strong", { key: "share" }, item.shareLabel),
        ]),
      ),
    ),
  ]);
}

function assetPreviewItems(stats) {
  const entry = stats?.rows?.find((row) => row.id === "entry")?.share || 0;
  const exit = stats?.rows?.find((row) => row.id === "exit")?.share || 0;
  return ASSET_PREVIEW_DEFS.map((asset) => ({
    ...asset,
    share: asset.id === "entry" ? entry : asset.id === "exit" ? exit : 0,
    shareLabel:
      asset.id === "entry" || asset.id === "exit"
        ? `${Math.round((asset.id === "entry" ? entry : exit) * 100)}%`
        : "资产",
  }));
}
